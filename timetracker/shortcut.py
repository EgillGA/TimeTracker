"""A Start Menu shortcut, so there is something for the taskbar to pin.

Windows does not offer to pin a running window on its own. "Pin to taskbar"
resolves the button back to a shortcut file carrying the same application id
as the window, and TimeTracker launches through Task Scheduler running
wscript.exe on a .vbs file - nothing a shortcut has ever pointed at. Without
one, the option is either missing or, worse, pins a bare pyw.exe with none of
our arguments.

This writes that shortcut directly through the shell's own COM interfaces
(IShellLink, IPersistFile, IPropertyStore) rather than pulling in a package,
so installing still needs nothing beyond the standard library.

Best-effort throughout, the same rule as win.py: a missing shortcut is an
annoyance, not a reason the program should not run.
"""

import ctypes
import uuid
from ctypes import wintypes

CLSCTX_INPROC_SERVER = 0x1
HRESULT = ctypes.c_long


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


# PROPVARIANT proper is a tagged union; only VT_LPWSTR is ever put in one
# here, so the union is stood in for by two 64-bit slots wide enough to hold
# it - InitPropVariantFromString and PropVariantClear own its real shape.
class PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("wReserved1", ctypes.c_ushort),
        ("wReserved2", ctypes.c_ushort),
        ("wReserved3", ctypes.c_ushort),
        ("data1", ctypes.c_ulonglong),
        ("data2", ctypes.c_ulonglong),
    ]


class IUnknownVtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", ctypes.CFUNCTYPE(
            HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))),
        ("AddRef", ctypes.CFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)),
        ("Release", ctypes.CFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)),
    ]


class IShellLinkWVtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", IUnknownVtbl._fields_[0][1]),
        ("AddRef", IUnknownVtbl._fields_[1][1]),
        ("Release", IUnknownVtbl._fields_[2][1]),
        ("GetPath", ctypes.CFUNCTYPE(
            HRESULT, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong)),
        ("GetIDList", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_void_p)),
        ("SetIDList", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_void_p)),
        ("GetDescription", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)),
        ("SetDescription", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_wchar_p)),
        ("GetWorkingDirectory", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)),
        ("SetWorkingDirectory", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_wchar_p)),
        ("GetArguments", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)),
        ("SetArguments", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_wchar_p)),
        ("GetHotkey", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ushort))),
        ("SetHotkey", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_ushort)),
        ("GetShowCmd", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int))),
        ("SetShowCmd", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_int)),
        ("GetIconLocation", ctypes.CFUNCTYPE(
            HRESULT, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int))),
        ("SetIconLocation", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)),
        ("SetRelativePath", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong)),
        ("Resolve", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)),
        ("SetPath", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_wchar_p)),
    ]


class IPersistFileVtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", IUnknownVtbl._fields_[0][1]),
        ("AddRef", IUnknownVtbl._fields_[1][1]),
        ("Release", IUnknownVtbl._fields_[2][1]),
        ("GetClassID", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID))),
        ("IsDirty", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p)),
        ("Load", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong)),
        ("Save", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int)),
        ("SaveCompleted", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_wchar_p)),
        ("GetCurFile", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p))),
    ]


class IPropertyStoreVtbl(ctypes.Structure):
    _fields_ = [
        ("QueryInterface", IUnknownVtbl._fields_[0][1]),
        ("AddRef", IUnknownVtbl._fields_[1][1]),
        ("Release", IUnknownVtbl._fields_[2][1]),
        ("GetCount", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))),
        ("GetAt", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(PROPERTYKEY))),
        ("GetValue", ctypes.CFUNCTYPE(
            HRESULT, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))),
        ("SetValue", ctypes.CFUNCTYPE(
            HRESULT, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))),
        ("Commit", ctypes.CFUNCTYPE(HRESULT, ctypes.c_void_p)),
    ]


def _prototype(dll_name, function_name, restype, argtypes):
    """Pin down a signature explicitly.

    Without it ctypes guesses from the arguments passed at each call site,
    which is exactly backwards for functions taking None/NULL for an optional
    pointer - the guess depends on what happened to be passed, not on the
    real parameter type.
    """
    try:
        function = getattr(getattr(ctypes.windll, dll_name), function_name)
    except (OSError, AttributeError):
        return
    function.restype = restype
    function.argtypes = argtypes


if hasattr(ctypes, "windll"):
    _prototype("ole32", "CoInitialize", HRESULT, [ctypes.c_void_p])
    _prototype("ole32", "CoUninitialize", None, [])
    _prototype("ole32", "CoCreateInstance", HRESULT, [
        ctypes.POINTER(GUID), ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)])
    _prototype("ole32", "PropVariantClear", HRESULT, [ctypes.POINTER(PROPVARIANT)])
    _prototype("ole32", "CoTaskMemAlloc", ctypes.c_void_p, [ctypes.c_size_t])

# VT_LPWSTR: the one variant type this module ever builds.
VT_LPWSTR = 31


def _guid(text):
    # bytes_le is the mixed-endian layout Windows GUIDs use on the wire -
    # exactly this struct - so no call into ole32 is needed just to parse one.
    return GUID.from_buffer_copy(uuid.UUID(text).bytes_le)


CLSID_SHELL_LINK = _guid("{00021401-0000-0000-C000-000000000046}")
IID_SHELL_LINK_W = _guid("{000214F9-0000-0000-C000-000000000046}")
IID_PERSIST_FILE = _guid("{0000010B-0000-0000-C000-000000000046}")
IID_PROPERTY_STORE = _guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")

# The one property this module ever writes: System.AppUserModel.ID.
PKEY_APPUSERMODEL_ID = PROPERTYKEY(
    fmtid=_guid("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"), pid=5)


def _vtable(pointer, vtable_type):
    address = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_void_p))[0]
    return ctypes.cast(address, ctypes.POINTER(vtable_type)).contents


def _release(pointer):
    if pointer:
        _vtable(pointer, IUnknownVtbl).Release(pointer)


def _query_interface(pointer, iid):
    out = ctypes.c_void_p()
    hr = _vtable(pointer, IUnknownVtbl).QueryInterface(pointer, ctypes.byref(iid), ctypes.byref(out))
    if hr != 0 or not out:
        return None
    return out


def _create_instance(clsid, iid):
    out = ctypes.c_void_p()
    hr = ctypes.windll.ole32.CoCreateInstance(
        ctypes.byref(clsid), None, CLSCTX_INPROC_SERVER, ctypes.byref(iid), ctypes.byref(out))
    if hr != 0 or not out:
        return None
    return out


def _string_variant(text):
    """A VT_LPWSTR PROPVARIANT holding text, in CoTaskMemAlloc'd memory.

    Propsys ships helpers for this (InitPropVariantFromString) but doesn't
    actually export them from propsys.dll under that name, so the variant is
    built by hand the way that helper would: allocate through the same
    allocator PropVariantClear expects to free through, copy the string in.
    """
    encoded = ctypes.create_unicode_buffer(text)
    address = ctypes.windll.ole32.CoTaskMemAlloc(ctypes.sizeof(encoded))
    if not address:
        return None
    ctypes.memmove(address, encoded, ctypes.sizeof(encoded))

    variant = PROPVARIANT()
    variant.vt = VT_LPWSTR
    variant.data1 = address
    return variant


def _set_app_id(link, app_id):
    """Stamp System.AppUserModel.ID onto the shortcut being built.

    This is what lets Windows connect a pinned shortcut back to the running
    window's own taskbar button - both wear win.APP_ID.
    """
    store = _query_interface(link, IID_PROPERTY_STORE)
    if store is None:
        return False
    try:
        variant = _string_variant(app_id)
        if variant is None:
            return False
        try:
            vtbl = _vtable(store, IPropertyStoreVtbl)
            if vtbl.SetValue(store, ctypes.byref(PKEY_APPUSERMODEL_ID), ctypes.byref(variant)) != 0:
                return False
            return vtbl.Commit(store) == 0
        finally:
            ctypes.windll.ole32.PropVariantClear(ctypes.byref(variant))
    finally:
        _release(store)


def create(path, target, arguments="", working_dir="", icon="", description="", app_id=None):
    """Write a .lnk at path pointing at target. True if it was written.

    Never raises: on anything but Windows, or if any step along the way
    fails, this returns False and leaves whatever was there before untouched.
    """
    if not hasattr(ctypes, "windll"):
        return False

    init = ctypes.windll.ole32.CoInitialize(None)
    # RPC_E_CHANGED_MODE: some other apartment model is already active on
    # this thread. The calls below don't need to own it, so that's fine -
    # just don't pair it with a CoUninitialize we have no right to make.
    owns_com = init in (0, 1)
    if init not in (0, 1, -2147417850):
        return False

    try:
        link = _create_instance(CLSID_SHELL_LINK, IID_SHELL_LINK_W)
        if link is None:
            return False
        try:
            shell = _vtable(link, IShellLinkWVtbl)
            if shell.SetPath(link, target) != 0:
                return False
            if arguments:
                shell.SetArguments(link, arguments)
            if working_dir:
                shell.SetWorkingDirectory(link, working_dir)
            if icon:
                shell.SetIconLocation(link, icon, 0)
            if description:
                shell.SetDescription(link, description)
            if app_id and not _set_app_id(link, app_id):
                return False

            persist = _query_interface(link, IID_PERSIST_FILE)
            if persist is None:
                return False
            try:
                return _vtable(persist, IPersistFileVtbl).Save(persist, path, True) == 0
            finally:
                _release(persist)
        finally:
            _release(link)
    finally:
        if owns_com:
            ctypes.windll.ole32.CoUninitialize()

"""Only one TimeTracker window at a time.

The scheduled task fires at 15:30 and again at logon. Unlocking the laptop
while the window is already open must not stack a second one on top of it,
each holding its own copy of the day and each able to submit it.
"""

import unittest

from timetracker.single_instance import SingleInstance


class Claiming(unittest.TestCase):
    def test_the_first_claim_succeeds(self):
        with SingleInstance("TimeTrackerTest-first") as lock:
            self.assertTrue(lock.acquired)

    def test_a_second_claim_while_the_first_is_held_fails(self):
        with SingleInstance("TimeTrackerTest-second") as first:
            self.assertTrue(first.acquired)
            with SingleInstance("TimeTrackerTest-second") as second:
                self.assertFalse(second.acquired)

    def test_the_name_is_released_when_the_first_finishes(self):
        with SingleInstance("TimeTrackerTest-third") as first:
            self.assertTrue(first.acquired)

        with SingleInstance("TimeTrackerTest-third") as again:
            self.assertTrue(again.acquired,
                            "a closed instance must not hold the name")

    def test_different_names_do_not_collide(self):
        with SingleInstance("TimeTrackerTest-a") as first:
            with SingleInstance("TimeTrackerTest-b") as second:
                self.assertTrue(first.acquired)
                self.assertTrue(second.acquired)

    def test_release_is_safe_to_call_twice(self):
        lock = SingleInstance("TimeTrackerTest-double-release")
        lock.acquire()
        lock.release()
        lock.release()

    def test_it_never_raises_even_if_the_platform_will_not_play(self):
        # Failing to take the lock must not stop the prompt appearing. A
        # duplicate window is a nuisance; no window at all defeats the tool.
        lock = SingleInstance("TimeTrackerTest-safe")
        self.assertIsInstance(lock.acquire(), bool)
        lock.release()


if __name__ == "__main__":
    unittest.main()

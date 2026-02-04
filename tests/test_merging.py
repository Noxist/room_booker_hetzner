import unittest
from datetime import datetime

from roombooker.calendar_sync import CalendarSync


class TestCalendarMerging(unittest.TestCase):
    def test_merge_consecutive_slots(self):
        slots = [
            {
                "start": datetime(2024, 1, 1, 8, 0),
                "end": datetime(2024, 1, 1, 12, 0),
                "room": "Raum 1",
            },
            {
                "start": datetime(2024, 1, 1, 12, 0),
                "end": datetime(2024, 1, 1, 16, 0),
                "room": "Raum 1",
            },
        ]

        merged = CalendarSync.merge_slots(slots)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].start, datetime(2024, 1, 1, 8, 0))
        self.assertEqual(merged[0].end, datetime(2024, 1, 1, 16, 0))
        self.assertEqual(merged[0].room, "Raum 1")


if __name__ == "__main__":
    unittest.main()

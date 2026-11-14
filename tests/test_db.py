"""Лидерборд: без яиц, один юзер — один питомец, сортировка и лимит."""
import json
import unittest

from storage.db import Db


def state_json(name='Пуся', stage=1, cs=10):
    return json.dumps({'n': name, 's': stage, 'cs': cs}, ensure_ascii=False)


class TestLeaderboard(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Db(':memory:')

    async def test_eggs_excluded(self):
        await self.db.save_pet(1, 100, None, state_json(stage=0, cs=0), 0, 0, 1)
        await self.db.save_pet(2, 100, None, state_json('пупуся', 1, 5), 0, 0, 2)
        rows = await self.db.list_pets()
        self.assertEqual([r['name'] for r in rows], ['пупуся'])

    async def test_one_user_one_row(self):
        # user_id — PRIMARY KEY: повторный save_pet обновляет строку, а не дублирует
        await self.db.save_pet(1, 100, None, state_json('A', 1, 1), 0, 0, 1)
        await self.db.save_pet(1, 100, None, state_json('B', 2, 9), 0, 0, 2)
        rows = await self.db.list_pets()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'B')

    async def test_sorted_and_limited(self):
        for i in range(12):
            await self.db.save_pet(100 + i, 100, None,
                                   state_json('p%d' % i, 1, i), 0, 0, i)
        rows = await self.db.list_pets(10)
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0]['care_score'], 11)


if __name__ == '__main__':
    unittest.main()

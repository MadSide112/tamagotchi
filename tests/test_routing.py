import unittest

from bot.handlers import classify

BOT = 'madNIMbot'
BOT_ID = 8694568616
USER_ID = 754216474
GROUP_ID = -5420583088


def msg(text=None, chat_type='group', reply_from=None):
    m = {'chat': {'id': GROUP_ID if chat_type != 'private' else USER_ID,
                  'type': chat_type},
         'from': {'id': USER_ID}}
    if text is not None:
        m['text'] = text
    if reply_from is not None:
        m['reply_to_message'] = {'from': {'id': reply_from}}
    return m


class TestGroupRouting(unittest.TestCase):
    def test_plain_chatter_ignored(self):
        self.assertEqual(classify(msg('привет всем'), BOT, BOT_ID)[0], 'ignored')

    def test_sticker_no_text_ignored(self):
        self.assertEqual(classify(msg(None), BOT, BOT_ID)[0], 'ignored')

    def test_mention_case_insensitive(self):
        kind, _, args = classify(msg('а что за @madnimbot тут?'), BOT, BOT_ID)
        self.assertEqual(kind, 'mention')

    def test_reply_to_bot_is_attention(self):
        kind, _, _ = classify(msg('спасибо!', reply_from=BOT_ID), BOT, BOT_ID)
        self.assertEqual(kind, 'mention')

    def test_reply_to_human_ignored(self):
        self.assertEqual(classify(msg('ок', reply_from=USER_ID), BOT, BOT_ID)[0], 'ignored')

    def test_own_command(self):
        kind, cmd, _ = classify(msg('/start'), BOT, BOT_ID)
        self.assertEqual((kind, cmd), ('command', 'start'))

    def test_command_addressed_to_me(self):
        kind, cmd, _ = classify(msg('/start@MadNIMbot'), BOT, BOT_ID)
        self.assertEqual((kind, cmd), ('command', 'start'))

    def test_command_for_other_bot_ignored(self):
        self.assertEqual(classify(msg('/start@other_bot'), BOT, BOT_ID)[0], 'ignored')

    def test_unknown_command_still_a_command(self):
        kind, cmd, _ = classify(msg('/ban'), BOT, BOT_ID)
        self.assertEqual((kind, cmd), ('command', 'ban'))

    def test_name_with_args_and_target(self):
        kind, cmd, args = classify(msg('/name@madNIMbot Пуся'), BOT, BOT_ID)
        self.assertEqual((kind, cmd, args), ('command', 'name', 'Пуся'))


class TestPrivateRouting(unittest.TestCase):
    def test_plain_text_answered(self):
        self.assertEqual(classify(msg('ку', chat_type='private'), BOT, BOT_ID)[0],
                         'private_text')

    def test_command_without_target(self):
        kind, cmd, args = classify(msg('/name Барсик', chat_type='private'), BOT, BOT_ID)
        self.assertEqual((kind, cmd, args), ('command', 'name', 'Барсик'))

    def test_sticker_private_ignored(self):
        self.assertEqual(classify(msg(None, chat_type='private'), BOT, BOT_ID)[0], 'ignored')


if __name__ == '__main__':
    unittest.main()

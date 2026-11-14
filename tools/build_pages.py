"""Build docs/index.html (GitHub Pages demo) from widget/template.html.

Run from the project root: python3 tools/build_pages.py
The demo embeds the widget with a TelegramWidget stub, as recommended by
the official widgets docs for browser testing.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

DEMO_STATE = {'r': 1, 'n': 'Пуся', 'h': 82, 'm': 64, 'e': 90, 'sl': 0,
              'sk': 0, 's': 4, 'cn': 42, 'wn': 'hat'}

STUB_TEMPLATE = '''<script>
document.documentElement.style.setProperty('--tg-theme-bg-color','#ffffff');
document.documentElement.style.setProperty('--tg-theme-text-color','#1c2733');
document.documentElement.style.setProperty('--tg-theme-hint-color','#8d969f');
document.documentElement.style.setProperty('--tg-theme-button-color','#2f9ce0');
document.documentElement.style.setProperty('--tg-theme-secondary-bg-color','#eef3f8');
document.documentElement.style.setProperty('--tg-theme-destructive-text-color','#e0482f');
const DEMO_ANSWER = JSON.stringify({m:'🚧 Это демо-превью: игра живёт в Telegram, у бота @madNIMbot'});
window.TelegramWidget={chatData:__CHAT_DATA__,
request:a=>new Promise(res=>setTimeout(()=>res({result:DEMO_ANSWER}),350)),
onEvent(){},ready(){},HapticFeedback:{notificationOccurred(){}}};
</script>'''

PAGE_TEMPLATE = '''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Telegram Tamagotchi Widget — Bot API 10.4</title>
<style>
body{margin:0;min-height:100vh;background:#e7f0f7;font-family:system-ui,-apple-system,sans-serif;display:flex;flex-direction:column;align-items:center;padding:28px 16px;box-sizing:border-box}
h1{font-size:20px;margin:0 0 4px;color:#1c2733;text-align:center}
.sub{font-size:13px;color:#5d6b7a;margin:0 0 20px;text-align:center;max-width:420px;line-height:1.5}
.card{background:#fff;border-radius:16px;box-shadow:0 2px 12px rgba(20,40,60,.14);overflow:hidden;width:100%;max-width:360px}
.foot{margin-top:18px;font-size:12px;color:#8d969f;text-align:center;max-width:420px;line-height:1.6}
.foot a{color:#2f9ce0}
</style>
</head>
<body>
<h1>🐣 Telegram Tamagotchi</h1>
<p class="sub">Питомец-тамагочи, который живёт прямо в пузыре сообщения — интерактивный виджет Telegram (Bot API 10.4, <code>sendWidget</code>). Экономика, стрики, болезнь, три ветки эволюции и аксессуары — ниже превью взрослого питомца в шляпе.</p>
<div class="card">
__STUB__
__TEMPLATE__
</div>
<p class="foot">Состояние питомца серверно-авторитарное: виджет только рисует и шлёт запросы.<br>
Из-за ограничения Telegram (с 13.11.2026 виджеты открыты не для всех ботов) бот ждёт Открытия — <a href="https://github.com/MadSide112/tamagotchi">репозиторий проекта</a>.</p>
</body>
</html>'''


def main() -> None:
    template = (ROOT / 'widget' / 'template.html').read_text(encoding='utf-8')
    stub = STUB_TEMPLATE.replace('__CHAT_DATA__',
                                 json.dumps(DEMO_STATE, ensure_ascii=False))
    page = PAGE_TEMPLATE.replace('__STUB__', stub).replace('__TEMPLATE__', template)
    out = ROOT / 'docs' / 'index.html'
    out.write_text(page, encoding='utf-8')
    print('written %s (%d bytes)' % (out, len(page.encode('utf-8'))))


if __name__ == '__main__':
    main()

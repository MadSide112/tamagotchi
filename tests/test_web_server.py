"""HTTP-выдача страницы мини-аппа: gzip, ETag/304 и заголовки кэша.

Туннель до клиента медленный, поэтому /app отдаётся сжатым, а повторные
открытия проходят как 304 без тела — страница перекачивается только
после реального изменения HTML.
"""
import gzip
import unittest

from aiohttp import ClientSession
from aiohttp.test_utils import TestClient, TestServer

from bot.server import build_web_app

HTML = ('<!doctype html><html><head><title>Питомец</title></head>'
        '<body>Привет, это тестовая страница мини-аппа</body></html>')


class TestServeApp(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TestClient(TestServer(build_web_app(object(), 'x:token', HTML)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_gzip_when_accepted(self):
        # auto_decompress=False, чтобы увидеть тело ровно как его отдаёт сервер.
        session = ClientSession(auto_decompress=False)
        try:
            url = self.client.server.make_url('/app')
            async with session.get(url, headers={'Accept-Encoding': 'gzip'}) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.headers.get('Content-Encoding'), 'gzip')
                self.assertEqual(resp.headers.get('Vary'), 'Accept-Encoding')
                body = await resp.read()
            self.assertEqual(gzip.decompress(body).decode('utf-8'), HTML)
        finally:
            await session.close()

    async def test_identity_when_no_gzip(self):
        # Клиент aiohttp по умолчанию шлёт 'gzip, deflate' — задаём identity явно.
        resp = await self.client.get('/app', headers={'Accept-Encoding': 'identity'})
        self.assertNotIn('Content-Encoding', resp.headers)
        self.assertEqual(await resp.text(), HTML)

    async def test_gzip_disabled_by_q_zero(self):
        resp = await self.client.get(
            '/app', headers={'Accept-Encoding': 'gzip;q=0, deflate'})
        self.assertNotIn('Content-Encoding', resp.headers)

    async def test_etag_and_cache_headers(self):
        resp = await self.client.get('/app')
        etag = resp.headers.get('ETag')
        self.assertTrue(etag and etag.startswith('"'))
        self.assertEqual(resp.headers.get('Cache-Control'), 'no-cache')

    async def test_revalidation_returns_304(self):
        first = await self.client.get('/app')
        etag = first.headers['ETag']
        second = await self.client.get('/app', headers={'If-None-Match': etag})
        self.assertEqual(second.status, 304)
        self.assertEqual(await second.read(), b'')

    async def test_changed_etag_returns_body(self):
        first = await self.client.get('/app')
        other = await self.client.get(
            '/app', headers={'If-None-Match': '"stale-etag"'})
        self.assertEqual(other.status, 200)
        self.assertEqual(await other.text(), HTML)


if __name__ == '__main__':
    unittest.main()

import base64
import io

from PIL import Image

from .. import util
from ._base import APIBase, Pixel


# todo: rate limits
# todo: figure out live receive pixel endpoint


class APICMPC(APIBase):
    base_url = 'https://pixels.cmpc.live/'
    endpoint_set_pixel = base_url + 'set'
    endpoint_get_pixels = base_url + 'fetch'
    endpoint_auth = base_url + 'auth'
    endpoint_stayalive = base_url + 'stayalive'

    stayalive_interval_ms = 10000
    stayalive_interval_seconds = stayalive_interval_ms // 1000
    canvas_size_assumed = {
        'width': 960,
        'height': 540,
    }

    def __init__(self, username: str, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.username = username
        self.subscriber = False
        self.moderator = False

        self.headers.update(
            {
                'Origin': 'https://yp16mcc6rrm08z5aq7weu0fyp81quy.ext-twitch.tv',
                'Referer': 'https://yp16mcc6rrm08z5aq7weu0fyp81quy.ext-twitch.tv/',
            }
        )

    async def open(self):
        await super().open()
        await self.session.post(self.endpoint_auth, headers=self.headers)

    async def get_pixels(self) -> Image.Image:
        async with self.session.get(
            url=self.endpoint_get_pixels,
            headers=self.headers
        ) as response:
            response_json = await response.json()
            dataurl = response_json['DataURL']

        image_b64 = dataurl.removeprefix('data:image/png;base64,')
        image_bytes = base64.b64decode(image_b64, validate=True)
        stream = io.BytesIO(image_bytes)
        image = Image.open(stream)
        return image

    async def set_pixel(self, x: int, y: int, colour: Pixel):
        payload = {
            'Username': self.username,
            'Substatus': self.subscriber,
            'X': x,
            'Y': x,
            'Color': util.rgb_to_hex(colour),
        }
        response = await self.session.post(
            self.endpoint_set_pixel,
            headers=self.headers,
            json=payload
        )
        return response

    async def get_size(self) -> dict[str, int]:
        canvas = await self.get_pixels()
        return {
            'width': canvas.width,
            'height': canvas.height,
        }

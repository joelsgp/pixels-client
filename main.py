#!/usr/bin/env python

import json
import typing
import re
import time
from pathlib import Path

import requests
from requests.structures import CaseInsensitiveDict
import PIL.Image


# todo: add display of canvas


__version__ = '2.7.0'


# modify this to change the order of priority or add/remove images
imgs = [
    "httpscmpclivetwitchtvcontrolmypc-utf-8,1x,(13,38).png",
    "httpsvflgg-utf-8,1x,(103,56).png",
    "JMcB-utf-8,1x,(75,5).png",
    "voxelfox,1x,(103,37).png",
    "cmpc,1x,(13,35).png",
    "jmcb,1x,(75,2).png",
    "pydispix,1x,(139,0).png",
]


CONFIG_FILE_PATH = Path('config.json')
IMGS_FOLDER = Path('imgs')
CANVAS_LOG_PATH = Path('canvas.log')
BASE_URL = 'https://pixels.pythondiscord.com'
SET_URL = f'{BASE_URL}/set_pixel'
GET_SIZE_URL = f'{BASE_URL}/get_size'
GET_PIXELS_URL = f'{BASE_URL}/get_pixels'
GET_PIXEL_URL = f'{BASE_URL}/get_pixel'
STARTUP_DELAY = 120


img_type = typing.List[typing.List[str]]


def three_ints_to_rgb_hex_string(rgb_ints: typing.List[int]) -> str:
    """Take a list of ints and convert it to a colour e.g. [255, 255, 255] -> ffffff."""
    rgb_hex = [hex(i) for i in rgb_ints]
    rgb_hex_strings = [str(h)[2:].rjust(2, '0') for h in rgb_hex]
    rgb_hex_string = ''.join(rgb_hex_strings)

    return rgb_hex_string


def three_bytes_to_rgb_hex_string(pixel: bytes) -> str:
    """Take three bytes and convert them to a colour."""
    rgb_ints = [b for b in pixel]
    return three_ints_to_rgb_hex_string(rgb_ints)


# mode of pil_img should be RGBA
def img_to_lists(pil_img: PIL.Image.Image) -> img_type:
    """Convert a PIL image to a 2d list of hex colour strings (None for transparent pixels)."""
    pixel_list_img = []
    for p in pil_img.getdata():
        # if alpha channel shows pixel is transparent, save None instead
        if p[3] == 0:
            pixel_list_img.append(None)
        else:
            pixel_list_img.append(three_ints_to_rgb_hex_string(p[:3]))

    dimensional_list_img = []
    for i in range(pil_img.height):
        w = pil_img.width
        dimensional_list_img.append(pixel_list_img[i*w:i*w + w])

    return dimensional_list_img


def scale_img(pil_img: PIL.Image.Image, scale: int) -> PIL.Image.Image:
    """Calculate the new size of a PIL image, resize and return it."""
    new_size = (
        pil_img.width // scale,
        pil_img.height // scale
    )
    return pil_img.resize(size=new_size, resample=PIL.Image.NEAREST)


class Zone:
    """An area of pixels on the canvas, to be maintained.

    Attrs:
        img_path -- path provided to constructor
        name -- name from filename
        scale -- scale from filename
        location -- co-ordinates on canvas of top-left corner
        width
        height
        area
        img -- a 2d list of hex colour strings, like run_for_img takes
    """
    img_name_regexp = re.compile(r'(.*),([0-9]*)x,\(([0-9]*),([0-9]*)\)')

    def __init__(self, img_path: typing.Union[str, Path]):
        """Load an image and calulcate its attributes.

        Args:
            img_path -- str or Path object to an image
        Its name should match Zone.img_name_regexp:
        name,scalex,(x,y)
        e.g.
        jmcb,10x,(75,2)
        This is used by the code.
        The image is resized and converted to a 2d list of hex colour strings.
        """
        if not isinstance(img_path, Path):
            img_path = Path(img_path)
        self.img_path = img_path

        filename = self.img_path.stem
        properties = re.match(self.img_name_regexp, filename)
        self.name = properties[1]
        self.scale = int(properties[2])
        self.location = {
            'x': int(properties[3]),
            'y': int(properties[4])
        }

        pil_img = PIL.Image.open(self.img_path)
        pil_img_rgb = pil_img.convert('RGBA')
        if self.scale != 1:
            pil_img_scaled = scale_img(pil_img_rgb, self.scale)
        else:
            pil_img_scaled = pil_img_rgb
        self.width = pil_img_scaled.width
        self.height = pil_img_scaled.height
        self.area = self.width * self.height
        self.img = img_to_lists(pil_img_scaled)

        self.area_not_transparent = self.area
        for row in self.img:
            for pixel in row:
                if pixel is None:
                    self.area_not_transparent -= 1

        print(
            f'Loaded zone {self.name}\n'
            f'    width:  {self.width}\n'
            f'    height: {self.height}\n'
            f'    area:   {self.area}'
        )


def load_zones(directory: Path, img_names: list) -> typing.List[Zone]:
    """Load zones that match img_names from directory and return them."""
    zones = []

    for img in img_names:
        for file in directory.iterdir():
            if file.name == img and file.is_file():
                zones.append(Zone(file))
                break

    return zones


def ratelimit(headers: CaseInsensitiveDict):
    """Given headers from a response, print info and sleep if needed."""
    if 'requests-remaining' in headers:
        requests_remaining = int(headers['requests-remaining'])
        print(f'{requests_remaining} requests remaining')
        if not requests_remaining:
            requests_reset = int(headers['requests-reset'])
            print(f'sleeping for {requests_reset} seconds')
            sleep_finish_time = time.asctime(time.localtime(time.time() + requests_reset))
            print(f'finish sleeping at {sleep_finish_time}')
            time.sleep(requests_reset)
    else:
        cooldown_reset = int(headers['cooldown-reset'])
        print(f'on cooldown\nsleeping for {cooldown_reset} seconds')
        sleep_finish_time = time.asctime(time.localtime(time.time() + cooldown_reset))
        print(f'finish sleeping at {sleep_finish_time}')
        time.sleep(cooldown_reset)


def set_pixel(x: int, y: int, rgb: str, headers: dict):
    """set_pixel endpoint wrapper."""
    payload = {
        'x': x,
        'y': y,
        'rgb': rgb,
    }
    r = requests.post(
        SET_URL,
        json=payload,
        headers=headers
    )
    print(r.json()['message'])

    ratelimit(r.headers)


def get_pixels(canvas_size: dict, headers: dict) -> img_type:
    """get_pixels endpoint wrapper.

    Returns as a 2d list of hex colour strings, like an img.
    """
    r = requests.get(
        GET_PIXELS_URL,
        headers=headers
    )
    ratelimit(r.headers)

    pixels_bytes = r.content
    with open(CANVAS_LOG_PATH, 'a') as canvas_log_file:
        canvas_log_file.write(f'{time.asctime()}\n{pixels_bytes}\n')
    canvas = []
    for y in range(canvas_size['height'] + 1):
        row = []
        for x in range(canvas_size['width'] + 1):
            index = (y * canvas_size['width'] * 3) + (x * 3)
            pixel = pixels_bytes[index:index+3]
            row.append(three_bytes_to_rgb_hex_string(pixel))
        canvas.append(row)

    return canvas


def get_pixel(x: int, y: int, headers: dict) -> str:
    """get_pixel endpoint wrapper."""
    params = {
        'x': x,
        'y': y
    }
    r = requests.get(
        GET_PIXEL_URL,
        params=params,
        headers=headers
    )
    ratelimit(r.headers)
    return r.json()['rgb']


def get_size(headers: dict) -> typing.Dict[str, int]:
    """get_size endpoint wrapper."""
    r = requests.get(
        GET_SIZE_URL,
        headers=headers
    )

    return r.json()


def run_for_img(img: img_type, img_location: dict, canvas_size: dict, headers: dict):
    """Given an img and the location of its top-left corner on the canvas, draw/repair that image."""
    print('Getting current canvas status')
    canvas = get_pixels(canvas_size, headers)
    print('Got current canvas status')

    for y_index, row in enumerate(img):
        for x_index, colour in enumerate(row):
            pix_y = img_location['y'] + y_index
            pix_x = img_location['x'] + x_index

            # get canvas every other time
            # getting it more often means better collaboration
            # but too often is too often
            if x_index % 2 == 0:
                print(f'Getting status of pixel at ({pix_x}, {pix_y})')
                canvas[pix_y][pix_x] = get_pixel(pix_x, pix_y, headers)
                print(f'Got status of pixel at ({pix_x}, {pix_y}), {canvas[pix_y][pix_x]}')

            if colour is None:
                print(f'Pixel at ({pix_x}, {pix_y}) is intended to be transparent, skipping')
            elif canvas[pix_y][pix_x] == colour:
                print(f'Pixel at ({pix_x}, {pix_y}) is {colour} as intended')
            else:
                print(f'Pixel at ({pix_x}, {pix_y}) will be made {colour}')
                set_pixel(x=pix_x, y=pix_y, rgb=colour, headers=headers)


def main():
    """Run the program for all imgs."""
    with open(CONFIG_FILE_PATH) as config_file:
        config = json.load(config_file)
    print('Loaded config')
    bearer_token = f"Bearer {config['token']}"
    headers = {
        "Authorization": bearer_token
    }

    print('Getting canvas size')
    canvas_size = get_size(headers)
    print(f'Canvas size: {canvas_size}')

    print(f'Loading zones to do from {IMGS_FOLDER}')
    zones_to_do = load_zones(IMGS_FOLDER, imgs)
    total_area = sum(z.area_not_transparent for z in zones_to_do)
    print(f'Total area: {total_area}')
    canvas_area = canvas_size['width'] * canvas_size['height']
    total_area_percent = round(((total_area / canvas_area) * 100), 2)
    print(f'Total area: {total_area_percent}% of canvas')

    # todo: fix duplicated code
    print(f'sleeping for {STARTUP_DELAY} seconds')
    sleep_finish_time = time.asctime(time.localtime(time.time() + STARTUP_DELAY))
    print(f'finish sleeping at {sleep_finish_time}')
    time.sleep(STARTUP_DELAY)
    while True:
        for zone in zones_to_do:
            img = zone.img
            img_location = zone.location

            print(f"img name: {zone.name}")
            print(f'img dimension x: {zone.width}')
            print(f'img dimension y: {zone.height}')
            print(f'img pixels: {zone.area_not_transparent}')
            run_for_img(img, img_location, canvas_size, headers)


if __name__ == '__main__':
    main()

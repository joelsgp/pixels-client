import json
import sys
import argparse
import asyncio
import logging as log
from pathlib import Path
from typing import Union

from PIL import Image

import api
import discord_mirror
import zone


# todo: further cleaning up
# todo: modularise to support different apis
# todo: cmpc pixels support
# todo: better rate limit handling?
# todo: legacy r/place support for kicks


__version__ = '4.0.0a'


CONFIG_FILE_PATH = Path('config.json')
IMAGES_FOLDER = Path('images')
CANVAS_LOG_PATH = Path('canvas.log')
DEBUG_LOG_PATH = Path('debug.log')
CANVAS_IMAGE_PATH = IMAGES_FOLDER / 'ignore' / 'canvas.png'
WORM_COLOUR = 'ff8983'
GMTIME = False

BLANK_PIXEL = 'ffffff'


image_type = list[list[str]]


# file handler for all debug logging with timestamps
file_handler = log.FileHandler(DEBUG_LOG_PATH, encoding='utf-8')
file_handler.setLevel(log.DEBUG)
file_formatter = log.Formatter('%(asctime)s:' + log.BASIC_FORMAT)
file_handler.setFormatter(file_formatter)
# stream handler for info level print-like logging
stream_handler = log.StreamHandler(stream=sys.stdout)
stream_handler.setLevel(log.INFO)
stream_formatter = log.Formatter()
stream_handler.setFormatter(stream_formatter)
log.basicConfig(
    level=log.DEBUG,
    handlers=[
        file_handler,
        stream_handler,
    ]
)
# don't fill up debug.log with other loggers
for logger_name in ('urllib3', 'PIL', 'discord'):
    log.getLogger(logger_name).setLevel(log.ERROR)


def get_parser() -> argparse.ArgumentParser:
    """Get this script's parser."""
    parser = argparse.ArgumentParser(
        description=f'load images and their coords from {IMAGES_FOLDER} and try to create/protect them'
    )

    parser.add_argument('--version', action='version', version=__version__)
    # parser.add_argument('-g', '--gui', action='store_true', help='run a live tkinter display of the canvas')

    return parser


def rgb_to_hex(rgb_ints: list[int]) -> str:
    """Take a list of ints and convert it to a colour e.g. [255, 255, 255] -> ffffff."""
    return '{:0<2x}{:0<2x}{:0<2x}'.format(*rgb_ints)


async def save_canvas_as_png(canvas_size, headers, path: Union[str, Path] = None):
    if path is None:
        path = CANVAS_IMAGE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    canvas_bytes = await api.get_pixels(canvas_size, headers, as_bytes=True)
    canvas_image = Image.frombytes(
        mode='RGB',
        size=(canvas_size['width'], canvas_size['height']),
        data=canvas_bytes
    )
    canvas_image.save(path)


async def run_for_img(img: img_type, img_location: dict, canvas_size: dict, headers: dict, bot):
    """Given an img and the location of its top-left corner on the canvas, draw/repair that image."""
    log.info('Getting current canvas status')
    canvas_bytes = await api.get_pixels(canvas_size, headers, as_bytes=True)
    canvas = img_bytes_to_dimensional_list(canvas_bytes, canvas_size)
    log.info('Got current canvas status')
    if bot is not None:
        log.info('Updating canvas mirror')
        await bot.update_mirror_from_id(canvas_bytes)

    for y_index, row in enumerate(img):
        hit_incorrect_pixel = False

        for x_index, colour in enumerate(row):
            pix_y = img_location['y'] + y_index
            pix_x = img_location['x'] + x_index
            
            coords_str_template = '({x}, {y})'
            max_coords_str = coords_str_template.format(
                x=canvas_size['height'], y=canvas_size['width']
            )
            max_coords_str_length = len(max_coords_str)
            pix_coords_str = coords_str_template.format(x=pix_x, y=pix_y)
            pix_coords_str = pix_coords_str.ljust(max_coords_str_length)

            if colour is None:
                log.info(f'Pixel at {pix_coords_str} is intended to be transparent, skipping')
                continue
            try:
                canvas[pix_y][pix_x]
            except IndexError:
                log.error(f'Pixel at {pix_coords_str} is outside of the canvas')
            # get canvas every other time
            # getting it more often means better collaboration
            # but too often is too often
            # also only do it if we've hit a zone that needs changing, to further prevent get_pixel rate limiting
            if hit_incorrect_pixel and x_index % 1 == 0:
                log.info(f'Getting status of pixel at {pix_coords_str}')
                canvas[pix_y][pix_x] = await api.get_pixel(pix_x, pix_y, headers)
                log.info(f'Got status of pixel at {pix_coords_str}, {canvas[pix_y][pix_x]}')
            if canvas[pix_y][pix_x] == colour:
                log.info(f'Pixel at {pix_coords_str} is {colour} as intended')
            elif colour == WORM_COLOUR:
                log.info('Oh, worm')
            else:
                hit_incorrect_pixel = True
                log.info(f'Pixel at {pix_coords_str} will be made {colour}')
                await api.set_pixel(x=pix_x, y=pix_y, rgb=colour, headers=headers)


async def run_protections(zones_to_do: list[zone.Zone], canvas_size: dict, headers: dict, bot):
    while True:
        try:
            for z in zones_to_do:
                log.info('working on next img'.center(100, '='))
                log.info(f"img name: {z.name}")
                log.info(f'img dimension x: {z.width}')
                log.info(f'img dimension y: {z.height}')
                log.info(f'img pixels: {z.area_not_transparent}')
                await run_for_img(z.image, z.location, canvas_size, headers, bot)
        except Exception as error:
            log.exception(error)


async def main():
    """Run the program for all imgs."""
    parser = get_parser()
    parser.parse_args()

    with open(CONFIG_FILE_PATH) as config_file:
        config = json.load(config_file)
    log.info('Loaded config')
    bearer_token = f"Bearer {config['token']}"
    headers = {
        "Authorization": bearer_token
    }

    log.info('Getting canvas size')
    canvas_size = await api.get_size(headers)
    log.info(f'Canvas size: {canvas_size}')

    if 'discord_mirror' in config and config['discord_mirror']['bot_token']:
        bot = discord_mirror.MirrorBot(
            channel_id=config['discord_mirror']['channel_id'], message_id=config['discord_mirror']['message_id'],
            canvas_size=canvas_size
        )
        log.info('Running discord bot for canvas mirror')
        asyncio.create_task(bot.start(config['discord_mirror']['bot_token']))
        await bot.wait_until_ready()
    else:
        bot = None

    log.info(f'Loading zones to do from {IMAGES_FOLDER}')
    zones_to_do = zone.load_zones(IMAGES_FOLDER, imgs)
    total_area = sum(z.area_not_transparent for z in zones_to_do)
    log.info(f'Total area: {total_area}')
    canvas_area = canvas_size['width'] * canvas_size['height']
    total_area_percent = round(((total_area / canvas_area) * 100), 2)
    log.info(f'Total area: {total_area_percent}% of canvas')

    log.info(f'Saving current canvas as png to {CANVAS_IMAGE_PATH}')
    await save_canvas_as_png(canvas_size, headers)
    await run_protections(zones_to_do, canvas_size, headers, bot)


if __name__ == '__main__':
    # todo: clean keyboardinterrupt shutdown
    asyncio.run(main())

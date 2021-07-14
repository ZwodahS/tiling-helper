#!/usr/bin/env python3

import json
import os
import sys
import rectpack

from PIL import Image

DOC="""

python3 tilepack.py {inputfile} {export_path}

the file will be exported as ${export_path}.json and ${export_path}.png
"""

def construct_frame(bmask, x, y, w, h):
    return {
        "filename": bmask,
        "frame": { "x": x, "y": y, "w": w, "h": h, },
        "spriteSourceSize": { "x": 0, "y": 0, "w": w, "h": h },
        "sourceSize": { "w": w, "h": h },
        "duration": 0,
        "rotated": False,
        "trimmed": False,
    }

class Packer:

    M0 = (255, 255, 255, 255)
    M1 = (0, 0, 0, 255)
    MB = (255, 0, 0, 255)

    ADD_PADDING = 0

    def __init__(self, filepath):
        self.img = Image.open(filepath)
        self.pixels = list(self.img.getdata())

        if (os.environ.get("PADDING") != None):
            self.ADD_PADDING = int(os.environ.get("PADDING"))

        # scan the image for the 3 color marker that we are using
        self.M0 = self.pixels[0];
        self.M1 = self.pixels[1];
        self.M2 = self.pixels[2];

    def match_marker(self, startInd, markers):
        rStart = startInd
        c = rStart
        for row in markers:
            for col in row:
                if self.pixels[c] != col:
                    return False
                c += 1
            rStart += self.img.width
            c = rStart

        return True


    def pack(self, export_path):
        # scan for the start line
        line = 0;
        self.LINE_MARKER = [[self.M1, self.M0, self.M0, self.M0, self.M1]]
        self.SQUARE_START_MARKER = [ [self.M1, self.M0], [self.M0, self.M1] ]
        self.SQUARE_END_MARKER = [ [self.M0, self.M1], [self.M1, self.M0] ]
        while line < len(self.pixels):
            if (self.match_marker(line * self.img.width, self.LINE_MARKER)):
                break
            line += 1

        # set line start
        self.line_start = line
        line += 1
        while line < len(self.pixels):
            if (self.match_marker(line * self.img.width, self.LINE_MARKER)):
                break
            line += 1
        # set line end
        self.line_end = line

        self.boxes = []

        # start scanning pixel by pixel to find a start marker
        c = self.line_start * self.img.width
        while c < self.line_end * self.img.width:
            if (self.match_marker(c, self.SQUARE_START_MARKER)):
                box = self.get_box(c)
                if box is not None:
                    self.boxes.append(box)
            c += 1

        # by here we will have all our boxes and their mask.
        # we create a new image and a new json file to pack them
        packer = rectpack.newPacker(rotation=False)
        packer.add_bin(512, 512)

        for ind, box in enumerate(self.boxes):
            packer.add_rect(box["width"] + (self.ADD_PADDING * 2), box["height"] + (self.ADD_PADDING * 2), ind)

        packer.pack()

        packed_image = Image.new('RGBA', (512, 512), 0x00000000)

        frames = {}
        for rect in packer.rect_list():
            box = self.boxes[rect[5]]
            box["pack_rect"] = rect

            targetRect = (
                rect[1] + self.ADD_PADDING,
                rect[2] + self.ADD_PADDING,
                rect[1] + rect[3] - self.ADD_PADDING,
                rect[2] + rect[4] - self.ADD_PADDING
            )

            cropped = self.img.crop((
                box["start"][0],
                box["start"][1],
                box["end"][0] + 1,
                box["end"][1] + 1,
            ))
            packed_image.paste(cropped, targetRect)

            if box["mask"] not in frames:
                frames[box["mask"]] = []


            frames[box["mask"]].append(construct_frame(box["mask"], rect[1], rect[2], rect[3], rect[4]))

        frames_list = []
        frame_tags = []
        for key, fs in frames.items():
            f_start = len(frames_list)
            for f in fs:
                frames_list.append(f)
            f_end = len(frames_list) - 1
            frame_tag = {
                "name": key,
                "from": f_start,
                "to": f_end,
                "direction": "forward"
            }
            frame_tags.append(frame_tag)

        exported_image = export_path+".png"
        packed_image.save(exported_image)

        packed_json = {
            "frames": frames_list,
            "meta": {
                "app": "tilepacker",
                "version": "0.0.1",
                "format": "RGBA8888",
                "size": { "w": 512, "h": 512 },
                "scale": 1,
                "frameTags": frame_tags
            }
        }
        with open(export_path+".json", "w") as f:
            print(json.dumps(packed_json, indent=2), file=f)

    def move_pixel(self, c, x, y):
        return c + x + (y * self.img.width)

    def get_box(self, start):
        # move diagonal down right by 1 pixel
        c = self.move_pixel(start, 1, 1)
        im_start = self.ind_to_pos(self.move_pixel(c, 1, 1))
        # scan until we no longer encount MB
        c = self.move_pixel(c, 1, 0)
        while (self.pixels[c] == self.MB):
            c += 1
        # this is the first pixel that is not the border
        # we need to go left by 2 pixel, and then down by 2 pixel
        c = self.move_pixel(c, -2, 1)

        while (self.pixels[c] == self.MB):
            c = self.move_pixel(c, 0, 1)

        # this should match the STOP_MARKER
        if not self.match_marker(c, self.SQUARE_END_MARKER):
            return None

        im_end = self.ind_to_pos(self.move_pixel(c, -1, -1))

        mask_start = self.pos_to_ind(im_start[0], im_end[1] + 1)

        im_width = im_end[0] - im_start[0] + 1
        im_height = im_end[1] - im_start[1] + 1

        mask = self.get_mask(mask_start)

        return {
            "start": im_start,
            "end": im_end,
            "width": im_width,
            "height": im_height,
            "mask": mask
        }

    def get_mask(self, mask_start):
        mask = []
        for i in range(0, 8):
            p = self.pixels[mask_start + i]
            if p == self.M0:
                mask.append("0")
            else:
                mask.append("1")
        return "".join(mask)

    def ind_to_pos(self, ind):
        return (ind % self.img.width, int(ind / self.img.width))

    def pos_to_ind(self, x, y):
        return x + (y * self.img.width)

def main():
    filepath = sys.argv[1]
    pack_name = sys.argv[2]
    packer = Packer(filepath)
    packer.pack(pack_name);

if __name__ == "__main__":
    main()

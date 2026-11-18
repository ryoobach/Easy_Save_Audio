from PIL import Image, ImageDraw

# Rounded cyan tile, blue music note, and a separate red play button.
SIZE = 256
im = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(im)

cyan = (139, 220, 230, 255)
blue = (62, 70, 205, 255)
red = (238, 47, 65, 255)
white = (255, 255, 255, 255)

d.rounded_rectangle((4, 4, 252, 252), radius=54, fill=cyan)

# Slightly compact two-note mark on the left.
d.ellipse((22, 166, 82, 226), fill=blue)
d.ellipse((88, 146, 148, 206), fill=blue)
d.rounded_rectangle((68, 48, 84, 185), radius=7, fill=blue)
d.rounded_rectangle((132, 34, 148, 164), radius=7, fill=blue)
d.polygon([(76, 48), (142, 32), (142, 49), (76, 65)], fill=blue)

# Separate play tile on the right; clear gap from the musical note.
d.rounded_rectangle((164, 88, 239, 168), radius=19, fill=red)
d.polygon([(190, 108), (190, 148), (221, 128)], fill=white)

im.save("easy_save_audio.png", format="PNG")
im.save("easy_save_audio.ico", format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])

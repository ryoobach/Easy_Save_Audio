from PIL import Image, ImageDraw

# Solid red app tile with a large white eighth note and white play symbol.
SIZE = 256
im = Image.new("RGBA", (SIZE, SIZE), (220, 32, 48, 255))
d = ImageDraw.Draw(im)

# White eighth note on the left.
white = (255, 255, 255, 255)
d.ellipse((24, 158, 94, 228), fill=white)
d.line((82, 178, 82, 48), fill=white, width=18)
d.line((82, 48, 148, 32), fill=white, width=18)
d.line((148, 32, 148, 158), fill=white, width=18)
d.ellipse((110, 136, 180, 206), fill=white)

# Enlarged white play triangle on the right.
d.polygon([(157, 91), (157, 194), (239, 142)], fill=white)

im.save("easy_save_audio.png", format="PNG")
im.save("easy_save_audio.ico", format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])

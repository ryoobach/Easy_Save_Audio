from PIL import Image, ImageDraw

# Original Easy Save Audio & Video icon: audio waveform + red play symbol.
im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.rounded_rectangle((12, 12, 244, 244), radius=52, fill=(28, 38, 54, 255))

# White eighth note, matching the established 1.2.0 visual identity.
note = (247, 249, 252, 255)
d.ellipse((35, 155, 91, 211), fill=note)
d.line((79, 174, 79, 49), fill=note, width=14)
d.line((79, 49, 139, 34), fill=note, width=14)
d.line((139, 34, 139, 153), fill=note, width=14)
d.ellipse((96, 130, 152, 186), fill=note)

# Red video tile with a white play triangle.
d.rounded_rectangle((157, 91, 229, 165), radius=19, fill=(225, 44, 58, 255))
d.polygon([(181, 106), (181, 150), (211, 128)], fill=(255, 255, 255, 255))

im.save("easy_save_audio.png", format="PNG")
im.save("easy_save_audio.ico", format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])

from PIL import Image, ImageDraw

# Original Easy Save Audio & Video icon: audio waveform + red play symbol.
im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.rounded_rectangle((12, 12, 244, 244), radius=52, fill=(28, 38, 54, 255))

# Audio waveform on the left.
wave_color = (245, 248, 252, 255)
bars = [(48, 104), (66, 72), (84, 124), (102, 88), (120, 60)]
for x, height in bars:
    y0 = (256 - height) // 2
    d.rounded_rectangle((x, y0, x + 10, y0 + height), radius=5, fill=wave_color)

# Distinct red video play triangle on the right (not a copied platform logo).
d.rounded_rectangle((148, 72, 224, 184), radius=22, fill=(225, 44, 58, 255))
d.polygon([(176, 96), (176, 160), (207, 128)], fill=(255, 255, 255, 255))

im.save("easy_save_audio.png", format="PNG")
im.save("easy_save_audio.ico", format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])

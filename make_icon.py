from PIL import Image, ImageDraw
im=Image.new("RGBA",(256,256),(201,29,46,255))
d=ImageDraw.Draw(im)
# White musical note: stem, flag and round note head
d.ellipse((72,151,145,216),fill="white")
d.rounded_rectangle((130,48,151,180),radius=8,fill="white")
d.polygon([(145,48),(205,64),(205,87),(145,72)],fill="white")
im.save("easy_save_audio.ico",format="ICO",sizes=[(256,256),(128,128),(64,64),(32,32),(16,16)])

im.save("easy_save_audio.png",format="PNG")

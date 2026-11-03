from PIL import Image,ImageDraw,ImageFont
W,H=1200,800
im=Image.new('RGB',(W,H),'#f4efec');d=ImageDraw.Draw(im)
d.rounded_rectangle((24,24,1176,776),radius=30,fill='white')
f='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';b='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
def text(x,y,t,size=24,bold=False,color='#251f21'):
 d.text((x,y),t,font=ImageFont.truetype(b if bold else f,size),fill=color)
def box(x,y,w,h,title,subtitle):
 d.rounded_rectangle((x,y,x+w,y+h),radius=18,fill='#f0f6f3',outline='#d5e3dd',width=2)
 text(x+20,y+18,title,25,True);text(x+20,y+64,subtitle,20,color='#585254')
def arrow(x,y,w=50):
 d.line((x,y,x+w,y),fill='#73a89a',width=5);d.polygon([(x+w,y),(x+w-12,y-9),(x+w-12,y+9)],fill='#73a89a')
text(64,55,'AIArchLab',23,True);text(64,102,'RelayHandoff v0.1.0',40,True);text(64,164,'New runtime. Same task.',29)
text(64,233,'Python',22,True);arrow(205,249,45);text(280,233,'Broker: state + ownership + receipt',22,True);arrow(790,249,45);text(865,233,'Node.js',22,True)
box(64,305,222,130,'Save','Checkpoint + files');arrow(296,367,35)
box(344,305,222,130,'PREPARED','Writes frozen');arrow(576,367,35)
box(624,305,222,130,'CLAIMED','Verify; no writes');arrow(856,367,35)
box(904,305,222,130,'ACK','New epoch writes')
# Separate new-owner continuation from old-owner rejection.
d.line((1015,446,1015,474,730,474,730,493),fill='#73a89a',width=4)
d.polygon([(730,505),(721,491),(739,491)],fill='#73a89a')
d.rounded_rectangle((640,505,1126,568),radius=14,fill='#f0f6f3',outline='#d5e3dd',width=2)
text(661,522,'New owner continues',24,True,color='#588a7c')
d.rounded_rectangle((64,505,470,568),radius=14,fill='white',outline='#c0bebf',width=2)
text(82,522,'Old owner writes after handoff',20,True)
d.line((470,537,516,537,516,609,604,609),fill='#a09b9d',width=4)
d.polygon([(615,609),(602,600),(602,618)],fill='#a09b9d')
d.ellipse((623,587,667,631),fill='#251f21');d.line((635,599,655,619),fill='white',width=4);d.line((655,599,635,619),fill='white',width=4)
text(688,592,'Stale writes rejected',23,True)
text(64,653,'Broker-scoped fencing. ACK is not task completion.',21,color='#585254')
text(64,682,'UI demo combines claim, verify and ACK.',20,color='#585254')
d.line((64,718,1135,718),fill='#eae9ea',width=2)
text(64,733,'Concept visualization | Single-node developer / controlled pilot',18,color='#585254')
text(940,733,'04 Nov 2026',16,color='#585254')
im.save('task-continuity-concept.png')

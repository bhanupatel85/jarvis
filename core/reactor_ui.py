"""Performance-driven cinematic HUD. State from Jarvis, energy from real audio."""
import math
from dataclasses import dataclass
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient, QLinearGradient, QCursor

@dataclass(frozen=True)
class Motion:
    name: str
    speed: float
    energy: float
    color: str
    detail: str


def motion_state(state, speaking, muted, amplitude):
    amp = max(0., min(1., float(amplitude)))
    if muted:
        return Motion('MUTED', .18, 0, '#77828d', 'MICROPHONE INPUT DISABLED')
    if speaking or state == 'SPEAKING':
        return Motion('SPEAKING', 1.25, amp, '#ffbd55', 'VOICE OUTPUT / AUDIO REACTIVE')
    if state == 'LISTENING':
        return Motion('LISTENING', .65, amp, '#72e4ed', 'MICROPHONE INPUT / AUDIO REACTIVE')
    if state in ('THINKING', 'PROCESSING'):
        return Motion('PROCESSING', 1.1, .1, '#ffc875', 'PROCESSING REQUEST')
    return Motion(str(state).replace('_', ' '), .34, 0, '#d8ac63', 'AWAITING SESSION ACTIVITY')


def zoom_target(name, energy, phase, reduced=False):
    if reduced:
        return 1.0
    if name == 'SPEAKING':
        return 1.035 + energy * .095 + .013 * math.sin(phase * 5.5)
    if name == 'LISTENING':
        return 1.015 + energy * .055 + .010 * math.sin(phase * 2.5)
    if name == 'PROCESSING':
        return .985 + .014 * math.sin(phase * 3)
    return 1.0 + .008 * math.sin(phase * 1.5)



def project_point(x, y, z, yaw, pitch, scale, cx, cy):
    """Rotate a 3-D point and perspective-project it onto the Qt canvas."""
    xx=x*math.cos(yaw)+z*math.sin(yaw)
    zz=-x*math.sin(yaw)+z*math.cos(yaw)
    yy=y*math.cos(pitch)-zz*math.sin(pitch)
    depth=y*math.sin(pitch)+zz*math.cos(pitch)
    perspective=3.8/(3.8-depth)
    return cx+xx*scale*perspective, cy+yy*scale*perspective, depth

def paint_reactor(self, event):
    p=QPainter(self)
    if not p.isActive():return
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    w,h=self.width(),self.height()
    p.fillRect(self.rect(),QColor('#060b10'))
    mode=motion_state(self.state,self.speaking,self.muted,self._amp_disp)
    # Integrating velocity avoids jumps when the state changes.
    now=self._core_phase
    if not hasattr(self,'_reactor_time'):
        self._reactor_time=now;self._reactor_angle=0.;self._reactor_energy=0.;self._reactor_zoom=1.;self._reactor_speed=mode.speed
    dt=max(0,min(.12,now-self._reactor_time));self._reactor_time=now
    blend=1-math.exp(-dt*7)
    self._reactor_speed += (mode.speed-self._reactor_speed)*blend
    self._reactor_angle += 0 if self.reduced_motion else dt*self._reactor_speed
    self._reactor_energy += (mode.energy-self._reactor_energy)*.24
    a=self._reactor_angle;e=self._reactor_energy
    cx,cy=w*.5,h*.46
    base_r=max(25,min(w*.295,h*.295,(h-128)/2.7))
    target=zoom_target(mode.name,e,now,self.reduced_motion)
    self._reactor_zoom += (target-self._reactor_zoom)*blend
    r=base_r*self._reactor_zoom
    gold=QColor('#eeb86b');accent=QColor(mode.color);dim=QColor('#24414b')
    def pen(color,width=1):p.setPen(QPen(color,width));p.setBrush(Qt.BrushStyle.NoBrush)
    def circle(radius,color,width=1):
        pen(color,width);p.drawEllipse(QPointF(cx,cy),radius,radius)
    def arc(radius,start,span,color,width=1):
        pen(color,width);p.drawArc(QRectF(cx-radius,cy-radius,2*radius,2*radius),int(start*16),int(span*16))
    def text(x,y,width,label,size=8,color='#7f9da5',align=Qt.AlignmentFlag.AlignLeft):
        p.setFont(QFont('Segoe UI',size));p.setPen(QColor(color));p.drawText(QRectF(x,y,width,22),align,label)
    # Architectural registration grid and corner brackets.
    pen(QColor(76,145,163,13),.5)
    for x in range(0,w,32):p.drawLine(x,0,x,h)
    for y in range(0,h,32):p.drawLine(0,y,w,y)
    for x,y,sx,sy in ((18,18,1,1),(w-18,18,-1,1),(18,h-18,1,-1),(w-18,h-18,-1,-1)):
        pen(QColor('#55717a'));p.drawLine(x,y,x+sx*24,y);p.drawLine(x,y,x,y+sy*24)
    text(34,28,w-68,'N E U R A L   E N G I N E',9,'#d9b883')
    text(34,28,w-68,'J / 01',9,'#557b86',Qt.AlignmentFlag.AlignRight)
    text(34,51,w-68,'VOLUMETRIC HOLOGRAPHIC CORE',7)
    glow=QRadialGradient(QPointF(cx,cy),r*1.4)
    glow.setColorAt(0,QColor(254,166,50,36+int(e*26)));glow.setColorAt(.7,QColor(31,91,100,15));glow.setColorAt(1,QColor(0,0,0,0))
    p.fillRect(self.rect(),glow)
    # Segmented concentric machinery, with independent counter-rotation.
    circle(r*1.06,QColor('#20343d'),.7)
    for i in range(120):
        t=i*math.tau/120
        inner=r*(1.015 if i%5 else .995);outer=r*1.045
        pen(QColor('#577883') if i%5 else gold,.65 if i%5 else 1.2)
        p.drawLine(QPointF(cx+math.cos(t)*inner,cy+math.sin(t)*inner),QPointF(cx+math.cos(t)*outer,cy+math.sin(t)*outer))
    for j in range(3):
        arc(r*.945,j*120+a*36,87,gold,2.8)
        arc(r*.91,j*120+a*36+12,43,QColor('#825c30'),.8)
    for j in range(8):
        arc(r*.825,j*45-a*46,30,QColor('#99e1e3') if j%3==0 else QColor('#547781'),3.3 if j%3==0 else 1.3)
    circle(r*.785,QColor('#24434c'),.65)
    # Perspective-rendered hologram. Pointer movement adds restrained parallax.
    pointer=self.mapFromGlobal(QCursor.pos())
    target_x=max(-1,min(1,(pointer.x()-cx)/max(1,w*.5))) if self.underMouse() else 0
    target_y=max(-1,min(1,(pointer.y()-cy)/max(1,h*.5))) if self.underMouse() else 0
    self._holo_x=getattr(self,'_holo_x',0)+(target_x-getattr(self,'_holo_x',0))*.08
    self._holo_y=getattr(self,'_holo_y',0)+(target_y-getattr(self,'_holo_y',0))*.08
    yaw=a*.55+self._holo_x*.2
    pitch=-.28+self._holo_y*.15
    scale=r*(.63+e*.025)
    def project(point):
        return project_point(*point,yaw,pitch,scale,cx,cy)
    # A translucent projection cone and elliptical emitter establish height.
    base_y=cy+r*.90
    beam=QLinearGradient(cx,cy,cx,base_y)
    beam.setColorAt(0,QColor(74,221,239,0));beam.setColorAt(1,QColor(74,221,239,24))
    path=QPainterPath();path.moveTo(cx-r*.45,base_y);path.lineTo(cx-r*.28,cy)
    path.lineTo(cx+r*.28,cy);path.lineTo(cx+r*.45,base_y);path.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen);p.setBrush(beam);p.drawPath(path)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for j in range(3):
        pen(QColor(107,225,235,150-j*35),1)
        p.drawEllipse(QRectF(cx-r*(.45+j*.055),base_y-r*(.07+j*.015),r*(.90+j*.11),r*(.14+j*.03)))
    # Depth-sort globe mesh and tilted satellites so back edges recede.
    segments=[]
    def line3(first,second,kind=0):
        aa=project(first);bb=project(second)
        segments.append(((aa[2]+bb[2])/2,aa,bb,kind))
    for latitude in range(-5,6):
        phi=latitude*math.pi/12
        points=[(math.cos(phi)*math.cos(k*math.tau/64),math.sin(phi),math.cos(phi)*math.sin(k*math.tau/64)) for k in range(65)]
        for aa,bb in zip(points,points[1:]):line3(aa,bb)
    for longitude in range(16):
        theta=longitude*math.tau/16
        points=[(math.cos(k*math.pi/48-math.pi/2)*math.cos(theta),math.sin(k*math.pi/48-math.pi/2),math.cos(k*math.pi/48-math.pi/2)*math.sin(theta)) for k in range(49)]
        for aa,bb in zip(points,points[1:]):line3(aa,bb)
    for j in range(3):
        tilt=j*1.05+a*.12
        points=[]
        for k in range(81):
            t=k*math.tau/80
            x,z=math.cos(t)*1.22,math.sin(t)*1.22
            points.append((x,z*math.sin(tilt),z*math.cos(tilt)))
        for aa,bb in zip(points,points[1:]):line3(aa,bb,1)
    for depth,aa,bb,kind in sorted(segments,key=lambda v:v[0]):
        alpha=int(35+max(0,min(1,(depth+1.5)/3))*155)
        color=QColor(255,190,95,alpha) if kind else QColor(91,224,239,alpha)
        pen(color,1.25 if kind else .65)
        p.drawLine(QPointF(aa[0],aa[1]),QPointF(bb[0],bb[1]))
    for i in range(220):
        z=1-2*(i+.5)/220;theta=i*2.399963
        radial=math.sqrt(1-z*z)
        x,y,depth=project((radial*math.cos(theta),z,radial*math.sin(theta)))
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(169,247,255,int(60+(depth+1)*75)))
        size=.65+max(0,depth)*1.1;p.drawEllipse(QPointF(x,y),size,size)
    # Luminous volumetric nucleus, leaving the mesh visible through it.
    iris=QRadialGradient(QPointF(cx,cy),r*.21*(1+e*.2))
    iris.setColorAt(0,QColor(239,255,255,240));iris.setColorAt(.20,QColor(135,246,255,200))
    iris.setColorAt(.50,QColor(64,211,235,75));iris.setColorAt(1,QColor(64,211,235,0))
    p.setPen(Qt.PenStyle.NoPen);p.setBrush(iris)
    p.drawEllipse(QPointF(cx,cy),r*.21*(1+e*.2),r*.21*(1+e*.2))
    # A moving scan plane follows the globe's depth, frozen in reduced motion.
    scan=0 if self.reduced_motion else math.sin(now*.8)*.72
    ring=math.sqrt(1-scan*scan)
    path=QPainterPath()
    for k in range(65):
        t=k*math.tau/64;xx,yy,_=project((ring*math.cos(t),scan,ring*math.sin(t)))
        path.moveTo(xx,yy) if not k else path.lineTo(xx,yy)
    pen(QColor(174,247,255,190),1.25);p.drawPath(path)
    # Sparse purposeful annotations around the principal visualization.
    for angle,label in ((-32,'AUDIO'),(145,'CONTEXT'),(220,'TOOLS')):
        t=math.radians(angle);x=cx+math.cos(t)*r*1.08;y=cy+math.sin(t)*r*1.08
        end=x+(28 if math.cos(t)>0 else -28)
        pen(QColor('#47636a'),.7);p.drawLine(QPointF(x,y),QPointF(end,y))
        text(end if end>x else end-68,y-19,68,label,7,'#7f9da5')
    bottom=cy+base_r*1.32
    text(10,bottom,w-20,mode.name,13,mode.color,Qt.AlignmentFlag.AlignCenter)
    text(10,bottom+27,w-20,mode.detail,7,'#7a939c',Qt.AlignmentFlag.AlignCenter)
    for i in range(65):
        envelope=(1-abs(i-32)/33)**.7
        height=2+e*30*envelope*(.55+.45*math.sin(i*.75+now*13))
        p.fillRect(QRectF(cx+(i-32)*4,bottom+72-height/2,2,height),accent)
    p.end()

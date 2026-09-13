"""Hand-authored 60 mm relief. Reference landmarks are positions, never heights.

The reference is the original 1000 x 500 photograph, each coin 460 px across.
All widths, heights and tooling constraints below are millimetres.
"""
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt, gaussian_filter, map_coordinates

BASE, BACKGROUND, RADIUS = 2.04, 0.12, 30.0
PPM, SIZE = 20, 1201
AXIS = np.linspace(-30, 30, SIZE)
X, Y = np.meshgrid(AXIS, -AXIS)


def world(points):
    return [((a - 248.5) * 30 / 230, (249 - b) * 30 / 230) for a, b in points]


def mask(points):
    im = Image.new('L', (SIZE, SIZE))
    ImageDraw.Draw(im).polygon([((x + 30) * PPM, (30 - y) * PPM) for x, y in points], fill=255)
    return np.asarray(im) > 0


def polygon(points, bevel=.45):
    points=np.asarray(world(points))
    # Round hand-traced corners without introducing spline overshoot at feather tips.
    for _ in range(2):
        nxt=np.roll(points,-1,axis=0)
        points=np.stack((.85*points+.15*nxt,.15*points+.85*nxt),axis=1).reshape(-1,2)
    inside = mask(points)
    d = distance_transform_edt(inside) / PPM
    t = np.clip(d / bevel, 0, 1)
    return gaussian_filter(t * t * (3 - 2 * t), .65)


def line(points, width):
    """Gaussian ridge/groove; width is full width at half maximum."""
    d = np.full(X.shape, np.inf)
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        dx, dy = bx - ax, by - ay
        t = np.clip(((X - ax) * dx + (Y - ay) * dy) / (dx * dx + dy * dy), 0, 1)
        d = np.minimum(d, np.hypot(X - ax - t * dx, Y - ay - t * dy))
    return np.exp(-.5 * (d / (width / 2.355)) ** 2)


def stroke(points, width):
    return line(world(points), width)


def mound(cx, cy, rx, ry):
    (cx, cy), (ex, ey) = world([(cx, cy), (cx + rx, cy + ry)])
    return np.exp(-.5 * (((X - cx) / (ex - cx)) ** 2 + ((Y - cy) / (ey - cy)) ** 2))


def edit_weight(x,y):
    """Compact support in reference pixels; outer 25% is a quintic seam."""
    px=x*230/30+248.5; py=249-y*230/30
    weights=[]
    for cx,cy,rx,ry in [(282,188,33,28),(333,184,23,29),(327,211,26,29)]:
        r=np.sqrt(((px-cx)/rx)**2+((py-cy)/ry)**2)
        t=np.clip((1-r)/.25,0,1)
        weights.append(t*t*t*(10+t*(-15+6*t)))
    return np.maximum.reduce(weights)


def obverse():
    z = np.zeros_like(X)
    # Shoulder and wrap silhouette; four major folds, no textile texture.
    cloth = polygon([(94,350),(132,316),(188,303),(225,295),(270,301),
                     (313,319),(345,327),(381,361),(402,404),(388,420),
                     (347,441),(295,455),(241,457),(190,446),(145,422),(113,390)])
    cloth_z = .40 + .36*mound(236,387,88,58)
    cloth_z += .22*stroke([(129,371),(193,378),(259,344),(303,320)], 2.8)
    cloth_z += .27*stroke([(203,436),(244,393),(290,361),(337,337)], 3.0)
    cloth_z += .20*stroke([(292,447),(313,406),(342,369)], 2.5)
    cloth_z -= .28*stroke([(160,406),(213,400),(267,363),(301,344)], 1.0)
    z = np.maximum(z, cloth * cloth_z)
    # Infant head and wrapping remain recognisable behind the shoulder.
    baby = polygon([(x,y+18) for x,y in [(105,292),(117,274),(143,266),(169,271),(187,290),
                    (202,307),(219,317),(207,334),(181,348),(149,356),
                    (122,349),(108,332),(101,309)]])
    baby_z = .44 + .58*mound(151,319,33,32)
    baby_z += .14*mound(196,336,12,12)
    baby_z -= .25*stroke([(120,305),(136,318),(152,340)], 1.1)
    baby_z -= .24*stroke([(143,298),(157,313),(173,339)], 1.0)
    baby_z -= .25*stroke([(182,338),(192,335),(202,337)], .8)
    z = z*(1-baby) + baby_z*baby
    neck = polygon([(218,254),(273,271),(323,278),(319,301),(302,320),
                    (274,329),(241,312),(213,300),(199,279)])
    z = z*(1-neck) + neck*(.60 + .35*mound(266,286,39,29))
    # Hair mass with broad locks and a simple braid.
    hair = polygon([(172,265),(165,238),(151,209),(151,176),(163,140),
                    (184,114),(215,99),(252,91),(283,94),(312,106),
                    (332,128),(348,155),(354,188),(365,210),(352,210),
                    (338,184),(322,156),(298,143),(272,166),(251,190),
                    (228,221),(219,251),(217,289),(206,309),(190,312),
                    (185,293),(191,267),(194,242),(176,258)])
    hair_z = .46 + .53*mound(239,156,67,58)
    for pts in [ [(160,218),(181,178),(222,140),(281,113)],
                 [(160,190),(185,151),(222,121),(259,104)],
                 [(178,235),(206,192),(249,152),(296,126)],
                 [(195,243),(223,204),(260,169),(310,142)] ]:
        hair_z -= .30*stroke(pts, .95)
    for cy in [252,270,288]:
        hair_z -= .27*stroke([(191,cy),(202,cy+6),(216,cy+1)], .85)
    z = z*(1-hair) + hair_z*hair
    # Cheek, brow, muzzle and chin are smooth volumes, independently of lighting.
    face = polygon([(228,223),(240,204),(253,184),(278,158),(302,137),
                    (320,141),(339,155),(348,177),(350,196),(351,211),
                    (354,223),(348,244),(344,262),(335,282),(318,294),
                    (294,294),(270,285),(249,272),(234,252)], .48)
    f = (.47 + .32*mound(290,166,32,30) + .43*mound(269,230,29,28)
         + .30*mound(337,227,15,23) + .21*mound(320,253,26,19)
         + .37*mound(309,279,24,13))
    foundation = f.copy()
    # Almond openings. Far eye is foreshortened, but still has an open pupil.
    f += .30*mound(333,184,10,11)
    for cx, cy, rx in [(282,191,14),(333,184,8.7)]:
        f -= .24*mound(cx,cy,rx*1.3,10)
        f += .10*mound(cx,cy,rx*.7,4)
        upper = [(cx-rx,cy),(cx-rx*.45,cy-4.5),(cx+rx*.35,cy-5),(cx+rx,cy)]
        lower = [(cx-rx,cy),(cx-rx*.45,cy+4),(cx+rx*.35,cy+4.5),(cx+rx,cy)]
        f += np.maximum(.54*stroke(upper,1.10),.54*stroke(lower,1.10))
        # A shallow iris disc and a recessed pupil give gaze without a raised pin.
        f += .10*mound(cx+1,cy,4.2,4.0)
        pupil_radius=3.0 if cx==282 else 3.2
        f -= (.58 if cx==282 else .63)*mound(cx+1,cy,pupil_radius,pupil_radius)
    f += .16*stroke([(266,177),(280,172),(294,176)],1.0)
    f += .14*stroke([(329,170),(336,168),(341,173)],.85)
    f += .48*stroke([(318,181),(319,196),(325,211)],1.5)
    f += .74*mound(331,219,6.5,6)
    f += .25*mound(316,225,5,4) + .16*mound(340,222,4,4)
    f -= .42*stroke([(313,230),(318,227),(323,230)],.85)
    f -= .25*stroke([(337,230),(341,226)],.8)
    # Replace the old eye/nose terms only inside compact interior supports.
    replacement = foundation.copy()
    for cx, cy, rx, strength in [(282,191,14,1.0),(333,184,8.7,.78)]:
        upper=[(cx-rx,cy),(cx-rx*.45,cy-4.5),(cx+rx*.35,cy-5),(cx+rx,cy)]
        replacement -= .24*mound(cx,cy,rx*1.3,10)
        replacement += strength*.27*stroke(upper,.85)
        replacement += strength*.065*mound(cx,cy+1,rx*.7,4.5)
        replacement -= strength*.13*stroke([(cx-rx*.65,cy),(cx,cy-.5),(cx+rx*.6,cy)],.65)
    replacement += .16*stroke([(266,177),(280,172),(294,176)],1.0)
    replacement += .14*stroke([(329,170),(336,168),(341,173)],.85)
    # A broad sloping bridge and elongated tip share one continuous volume.
    replacement += .43*stroke([(318,181),(320,198),(327,216)],1.9)
    replacement += .15*mound(329,217,9,10)
    replacement += .10*mound(316,225,7,5) + .07*mound(340,222,5,5)
    replacement -= .14*stroke([(315,228),(320,227)],.65)
    replacement -= .10*stroke([(338,228),(341,226)],.6)
    weight = edit_weight(X,Y)
    f = f + weight*(replacement-f)
    f += .25*stroke([(301,248),(313,244),(323,246),(332,244),(344,247)],1.3)
    f += .29*mound(323,258,13,4.5)
    f -= .34*stroke([(300,252),(311,252),(322,251),(333,249),(345,248)],.85)
    z = z*(1-face) + f*face
    # Ear ridge sits between face and braid.
    z += .19*stroke([(231,230),(221,228),(217,240),(222,251),(231,247)],1.0)
    return z


def reverse():
    z = np.zeros_like(X)
    # Local coordinates are the reverse half of reference.jpg minus 500 px.
    wing = polygon([(266,293),(260,258),(264,219),(266,183),(262,153),
                    (246,115),(233,91),(246,100),(276,143),(263,107),
                    (252,81),(267,91),(289,133),(278,91),(280,71),
                    (293,89),(302,132),(304,88),(312,76),(318,103),
                    (319,148),(327,113),(338,99),(337,141),
                    (326,183),(316,212),(315,245),(323,276),(316,300)])
    wz = .43 + .52*mound(290,206,24,78)
    # Five primary divisions and three broad coverts replace feather scales.
    for pts in [[(266,169),(249,118)],[(277,177),(273,119)],
                [(289,182),(290,118)],[(301,183),(308,119)],
                [(309,195),(327,145)]]:
        wz -= .28*stroke(pts, .95)
    for cy in [211,236,261]:
        wz -= .31*stroke([(268,cy-6),(285,cy+4),(310,cy-2)],1.0)
    z = np.maximum(z, sample(wing*wz,X-1.0,Y/.95))
    tail = polygon([(315,306),(348,296),(374,298),(390,312),
                    (391,331),(379,349),(354,355),(332,343),(312,333)])
    tz = .44 + .42*mound(351,325,28,17)
    for pts in [[(334,312),(376,311)],[(338,322),(382,324)],[(335,332),(373,339)]]:
        tz -= .44*stroke(pts,.95)
    z = np.maximum(z,tail*tz)
    lower = polygon([(272,307),(290,323),(284,342),(257,355),(226,366),
                     (189,374),(153,371),(123,360),(100,346),(86,326),
                     (87,314),(101,333),(118,341),(108,320),(119,324),
                     (135,345),(149,348),(139,330),(153,335),(167,350),
                     (188,351),(216,343),(243,327)])
    lz = .43 + .43*mound(216,346,67,18)
    for pts in [[(127,346),(140,359)],[(153,350),(163,364)],
                [(180,351),(185,368)],[(208,347),(212,363)],
                [(236,339),(241,355)],[(259,328),(268,344)]]:
        lz -= .28*stroke(pts,.95)
    z = np.maximum(z,lower*lz)
    body = polygon([(191,301),(201,294),(215,291),(235,296),(260,292),
                    (279,285),(296,290),(312,302),(338,308),(350,321),
                    (337,337),(313,344),(285,340),(266,330),(246,331),
                    (224,322),(215,311),(202,308),(190,309),(183,305)])
    bz = .49 + .90*mound(288,316,33,17) + .26*mound(218,303,16,11)
    bz -= .25*stroke([(255,313),(276,323),(302,329)],1.0)
    bz -= .24*stroke([(285,298),(298,309),(321,316)],.95)
    bz -= .30*mound(208,300,3.1,3.1)
    bz -= .26*stroke([(187,306),(199,303)],.8)
    z = z*(1-body) + body*bz
    # Seventeen broad stars preserve the ring; pointed ends are supported tips.
    for cx,cy in star_centers():
        pts=[]
        for k in range(10):
            a = np.pi/2 + k*np.pi/5
            r = 9.0 if k%2==0 else 4.7
            pts.append((cx+r*np.cos(a),cy-r*np.sin(a)))
        z = np.maximum(z, .60*polygon(pts,.22))
    return z


def star_centers():
    landmarks=[(177,90),(139,110),(112,144),(99,166),(95,239),
               (96,266),(111,299),(371,161),(390,197),(398,237),
               (389,276),(342,374),(306,392),(263,401),(221,401),
               (180,390),(224,86)]
    return [(cx,cy) if cy>=370 else (248.5+.90*(cx-248.5),249+.90*(cy-249))
            for cx,cy in landmarks]


# Original monoline uppercase outlines: a stable font with deliberately open counters.
# Coordinates span x=0..1, y=0..1. Paths are swept with a round 0.8 mm stroke.
GLYPHS = {
 'A': [[(0,0),(0,.83),(.2,1),(.8,1),(1,.83),(1,0)],[(0,.34),(1,.34)]],
 'B': [[(0,0),(0,1),(.9,1),(1,.93),(1,.57),(.9,.50),(0,.50)],[(.9,.50),(1,.43),(1,.07),(.9,0),(0,0)]],
 'C': [[(1,.88),(.7,1),(.25,1),(0,.75),(0,.25),(.25,0),(.7,0),(1,.12)]],
 'D': [[(0,0),(0,1),(.55,1),(1,.75),(1,.25),(.55,0),(0,0)]],
 'E': [[(1,1),(0,1),(0,0),(1,0)],[(0,.5),(.8,.5)]],
 'F': [[(0,0),(0,1),(1,1)],[(0,.52),(.85,.52)]],
 'G': [[(1,.98),(.25,1),(0,.75),(0,.25),(.25,0),(1,0),(1,.32),(.55,.32)]],
 'I': [[(.5,0),(.5,1)]],
 'L': [[(0,1),(0,0),(1,0)]],
 'M': [[(0,0),(0,1),(.5,.48),(1,1),(1,0)]],
 'N': [[(0,0),(0,1),(1,0),(1,1)]],
 'O': [[(.25,0),(0,.25),(0,.75),(.25,1),(.75,1),(1,.75),(1,.25),(.75,0),(.25,0)]],
 'P': [[(0,0),(0,1),(.7,1),(1,.78),(1,.62),(.7,.43),(0,.43)]],
 'R': [[(0,0),(0,1),(.9,1),(1,.93),(1,.50),(.9,.43),(0,.43)],[(.55,.43),(1,0)]],
 'S': [[(1,.87),(.73,1),(.25,1),(0,.78),(.05,.61),(.9,.4),(1,.2),(.75,0),(.25,0),(0,.14)]],
 'T': [[(0,1),(1,1)],[(.5,1),(.5,0)]],
 'U': [[(0,1),(0,.22),(.25,0),(.75,0),(1,.22),(1,1)]],
 'V': [[(0,1),(.5,0),(1,1)]],
 'W': [[(0,1),(.18,0),(.5,.53),(.82,0),(1,1)]],
 'Y': [[(0,1),(.5,.5),(1,1)],[(.5,.5),(.5,0)]],
 '0': [[(.25,0),(0,.25),(0,.75),(.25,1),(.75,1),(1,.75),(1,.25),(.75,0),(.25,0)]],
 '2': [[(0,.8),(.25,1),(.75,1),(1,.8),(1,.65),(0,0),(1,0)]],
}


def lettering(side):
    """Return the text height field for one side."""
    im = Image.new('L',(SIZE,SIZE))
    draw = ImageDraw.Draw(im)

    def put(text, center=None, h=2.6, w=1.7, pitch=3.2, radius=None, start=None, end=None, bottom=False):
        advances=np.array([0 if c=='I' else w for c in text])
        positions=np.cumsum(advances)-advances/2+np.arange(len(text))*(pitch-w)
        positions-=(positions[0]-advances[0]/2+positions[-1]+advances[-1]/2)/2
        for i,ch in enumerate(text):
            if ch==' ':
                continue
            if radius is None:
                origin=np.array([center[0]+positions[i],center[1]])
                u,v=np.array([1.,0.]),np.array([0.,1.])
            else:
                a=np.deg2rad(start+(end-start)*i/(len(text)-1))
                origin=radius*np.array([np.cos(a),np.sin(a)])
                u=np.array([-np.sin(a),np.cos(a)]) if bottom else np.array([np.sin(a),-np.cos(a)])
                v=-origin/radius if bottom else origin/radius
            for p in GLYPHS[ch]:
                q=[origin+(x-.5)*w*u+(y-.5)*h*v for x,y in p]
                pixels=[((x+30)*PPM,(30-y)*PPM) for x,y in q]
                draw.line(pixels,fill=255,width=21,joint='curve')
                for px,py in pixels:
                    draw.ellipse((px-10,py-10,px+10,py+10),fill=255)
    if side=='obverse':
        put('LIBERTY',h=3.5,w=2.2,radius=25.5,start=134,end=46)
        for word,y in [('IN',13.2),('GOD',8.2),('WE',3.2),('TRUST',-1.8)]:
            put(word,(-19.4,y),h=3.0,w=1.7,pitch=3.5)
        put('2000',(18.6,-7.5),h=3.0,w=1.7,pitch=3.5)
    else:
        put('UNITED STATES OF AMERICA',h=3.2,w=1.70,radius=25.7,start=182,end=-2)
        put('ONE DOLLAR',h=3.2,w=1.95,radius=25.6,start=224,end=316,bottom=True)
        put('E',(-9.5,10.7),h=2.8,w=1.9)
        put('PLURIBUS',(-9.5,5.7),h=3.4,w=1.65,pitch=3.3)
        put('UNUM',(-9.5,.6),h=3.0,w=1.7,pitch=3.5)
    inside=np.asarray(im)>0
    # A small edge bevel retains a broad flat crest and open counters.
    d=distance_transform_edt(inside)/PPM
    return .72*np.clip(d/.12,0,1)


def surface(side):
    z = obverse() if side=='obverse' else reverse()
    text=lettering(side)
    # Text lives on clean background. Do not blur either it or the finished face.
    z=np.maximum(z,text)
    r=np.hypot(X,Y)
    rim=.96*np.clip((r-28.55)/.35,0,1)-.20*np.clip((r-29.7)/.3,0,1)
    z=np.where(r>28.55,rim,z)
    return BASE+BACKGROUND+z


def sample(field,x,y):
    return map_coordinates(field,[(30-y)*PPM,(x+30)*PPM],order=1,mode='nearest')

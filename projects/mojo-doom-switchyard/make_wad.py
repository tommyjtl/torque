"""Build SWITCHYARD, an original three-sector PWAD for the Mojo room milestone."""
import math
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent
def name(s):
    return s.encode('ascii').ljust(8, b'\0')

def pack(fmt, *values):
    return struct.pack('<' + fmt, *values)

def build():
    # Clockwise boundaries: front sidedef lies on the right of its linedef.
    rooms = [
        [(0,0),(0,192),(256,192),(256,132),(256,60),(256,0)],
        [(256,60),(256,132),(288,132),(288,60)],
        [(288,0),(288,60),(288,132),(288,192),(544,192),(544,0)],
    ]
    vertices, lines, sides, segs, leaves = [], [], [], [], []
    def vertex(p):
        if p not in vertices: vertices.append(p)
        return vertices.index(p)
    for sector, polygon in enumerate(rooms):
        leaves.append(pack('HH', len(polygon), len(segs)))
        for a,b in zip(polygon,polygon[1:]+polygon[:1]):
            v,w=vertex(a),vertex(b)
            side=len(sides)
            reverse=next((i for i,l in enumerate(lines) if l[0:2]==[w,v]),None)
            door=a[0]==b[0] and a[0] in (256,288) and {a[1],b[1]}=={60,132}
            exit_line=a[0]==b[0]==544
            sides.append(pack('hh8s8s8sh',0,0,name('SHUTTER' if door else '-'),name('-'),name('-' if door else 'EXITWALL' if exit_line else 'BULKHEAD'),sector))
            if reverse is None:
                line=len(lines); direction=0
                lines.append([v,w,4 if door else 1,1 if door else 11 if exit_line else 0,0,side,65535])
            else:
                line=reverse; direction=1;lines[line][6]=side
            angle=round(math.atan2(b[1]-a[1],b[0]-a[0])*65536/(2*math.pi))%65536
            segs.append(pack('6H',v,w,angle,line,direction,0))
    def box(a,b): return (192,0,a,b)
    # Upwards split: child zero on east, child one on west.
    nodes=pack('12h2H',288,0,0,192,*box(288,544),*box(256,288),0x8002,0x8001)
    nodes+=pack('12h2H',256,0,0,192,*box(256,544),*box(0,256),0,0x8000)
    sectors=b''.join(pack('hh8s8shhh',0,h,name('DECK'),name('SOFFIT'),light,0,0) for h,light in [(96,208),(0,160),(96,240)])
    # SECTORS/LINES etc. use DOOM's on-disk records. BLOCKMAP has one list per shared region.
    cols,rows=5,2
    blockmap=pack('hhhh',0,0,cols,rows)+pack('H'*cols*rows,*([4+cols*rows]*(cols*rows)))+pack('H'*(len(lines)+2),0,*range(len(lines)),65535)
    lumps=[('MAP01',b''),('THINGS',pack('hhhhh',64,96,0,1,7)+pack('hhhhh',434,96,0,2028,7)),
           ('LINEDEFS',b''.join(pack('7H',*l) for l in lines)),('SIDEDEFS',b''.join(sides)),
           ('VERTEXES',b''.join(pack('hh',*p) for p in vertices)),('SEGS',b''.join(segs)),
           ('SSECTORS',b''.join(leaves)),('NODES',nodes),('SECTORS',sectors),('REJECT',bytes(2)),('BLOCKMAP',blockmap)]
    ramps=[(103,115,116),(111,144,144),(107,117,104),(176,106,70),(223,159,81),(90,229,202),(187,205,202),(254,216,136),
           (81,96,105),(105,81,79),(94,136,119),(228,93,67),(162,141,108),(223,210,179),(119,166,202),(252,246,216)]
    palette=bytes(round(c*(.10+.90*(i/15)**1.35)) for rgb in ramps for i in range(16) for c in rgb)
    cmap=bytes((i//16)*16+max(0,round((i%16)*(1-k/36))) for k in range(32) for i in range(256))
    def tex(mat,x,y):
        noise=((x*197+y*113+x*y*13)^(x<<2))%3
        if mat==0:  # riveted pressure panels, ceramic inserts and amber service stripe
            if y in (8,9):return 4*16+12
            if 11<y<16:return 8*16+5+(x//3)%2
            if x in (0,31,32,63) or y in (0,31,63):return 8*16+4
            if 5<=x%32<=25 and 24<=y<=52:return 1*16+8+noise-(2 if x%32 in (5,25) or y in (24,52) else 0)
            if x%32 in (3,28) and y%32 in (3,28):return 6*16+13
            return 8*16+8+noise
        if mat==1:
            if 6<y<18 or 47<y<55:return 4*16+14 if ((x+y)//9)%2 else 8*16+3
            if x%32 in (0,1,31):return 8*16+2
            return 3*16+7+noise+(2 if y%8==0 else 0)
        if mat==2:
            if 13<y<32 and 8<x<55:
                arrow=(17<x<41 and 20<y<25) or (36<=x<49 and abs(y-22)<(49-x))
                return 5*16+(15 if arrow else 4)
            return tex(0,x,y)
        if mat==3:return 2*16+(3 if x%32<2 or y%32<2 else 8+noise)
        if mat==4:return (6*16+14 if 8<x<54 and 15<y<19 else 8*16+(4 if x%32<2 or y%32<2 else 7+noise))
        # Original signal lamp billboard; index zero denotes the transparent cutout.
        w=abs(x-32)
        if 9<y<33 and w<16:return 5*16+(15 if w<11 and 14<y<26 else 8)
        if (32<=y<56 and w<6) or (54<=y<60 and w<20) or (6<=y<=10 and w<13):return 3*16+11
        return 0
    textures=[bytes(tex(i,x,y) for y in range(64) for x in range(64)) for i in range(6)]
    # Alongside standard map geometry use one indexed atlas for this first slice.
    lumps += [('PLAYPAL',palette),('COLORMAP',cmap),('SWATLAS',b''.join(textures))]
    # Compact status legends. Rasterized during asset generation, positioned by Mojo.
    glyphs={'A':'2/5/7/5/5','B':'6/5/6/5/6','C':'3/4/4/4/3','D':'6/5/5/5/6','E':'7/4/6/4/7','F':'7/4/6/4/4','G':'3/4/5/5/3','H':'5/5/7/5/5','I':'7/2/2/2/7','J':'1/1/1/5/2','K':'5/5/6/5/5','L':'4/4/4/4/7','M':'5/7/7/5/5','N':'5/7/7/7/5','O':'2/5/5/5/2','P':'6/5/6/4/4','Q':'2/5/5/7/3','R':'6/5/6/5/5','S':'3/4/2/1/6','T':'7/2/2/2/2','U':'5/5/5/5/7','V':'5/5/5/5/2','W':'5/5/7/7/5','X':'5/5/2/5/5','Y':'5/5/2/2/2','Z':'7/1/2/4/7','0':'7/5/5/5/7','1':'2/6/2/2/7','2':'6/1/2/4/7','3':'6/1/2/1/6','4':'5/5/7/1/1','5':'7/4/6/1/6','6':'3/4/6/5/2','7':'7/1/2/2/2','8':'2/5/2/5/2','9':'2/5/3/1/6','/':'1/1/2/4/4',' ':'0/0/0/0/0','-':'0/0/7/0/0'}
    labels=['SWITCHYARD','01 / INTAKE','02 / RELAY','AIRLOCK','SPACE / OPEN','SPACE / EXIT','PULSE THE RELAY','EXIT REACHED','SIGNAL LIVE','F5 SAVE   F9 LOAD   0 EXIT','SAVED','RESTORED','NO VALID SAVE','CLICK TO CAPTURE','USE THE GREEN EXIT','WASD MOVE   MOUSE TURN','CLICK FIRE   SPACE USE','K0 8/2 MOVE   4/6 TURN','K0 1 FIRE   ENTER USE','TAB HELP   0 EXIT','ENTER TO RESTART']
    art=bytearray(len(labels)*128*6)
    for i,label in enumerate(labels):
        for j,g in enumerate(label):
            for y,row in enumerate(map(int,glyphs[g].split('/'))):
                for x in range(3):
                    if row & (4>>x):art[(i*6+y)*128+j*4+x]=1
    lumps.append(('SWLABELS',bytes(art)))
    body=bytearray();directory=b''
    for n,d in lumps:
        directory+=pack('ii8s',12+len(body),len(d),name(n));body.extend(d)
    (ROOT/'assets/switchyard.wad').write_bytes(pack('4sii',b'PWAD',len(lumps),12+len(body))+body+directory)
if __name__=='__main__':build()

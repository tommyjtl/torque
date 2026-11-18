"""Prepare E1M1 render geometry and texture placement for personal use with DOOM1.WAD.

The index contains offsets into the original IWAD. No image or sound bytes are copied.
"""
from collections import Counter
import hashlib
import math
from pathlib import Path
import struct
import sys

SHA256 = '1d7d43be501e67d927e415e0b8f3e29c3bf33075e859721816f652a526cac771'

def read_name(data):
    return data.rstrip(b'\0').decode('ascii').upper()

def compile_index(path):
    wad = path.read_bytes()
    if hashlib.sha256(wad).hexdigest() != SHA256:
        raise ValueError('This milestone supports the unmodified id DOOM shareware 1.9 IWAD.')
    magic, count, directory = struct.unpack_from('<4sii', wad)
    entries = [(read_name(n),o,l) for o,l,n in struct.iter_unpack('<ii8s',wad[directory:])]
    lumps = {n:(o,l) for n,o,l in entries}
    marker = next(i for i,item in enumerate(entries) if item[0]=='E1M1')
    map_lumps = {n:(o,l) for n,o,l in entries[marker+1:marker+11]}
    def lump(n,table=lumps):
        o,l=table[n]
        return wad[o:o+l]
    def records(fmt,n):return list(struct.iter_unpack('<'+fmt,lump(n,map_lumps)))
    vertices=records('hh','VERTEXES'); lines=records('7H','LINEDEFS')
    sides=records('hh8s8s8sH','SIDEDEFS'); secs=records('hh8s8shhh','SECTORS')
    segs=records('6H','SEGS'); leaves=records('2H','SSECTORS');nodes=records('12h2H','NODES')
    pnames=lump('PNAMES'); patches=[read_name(pnames[i:i+8]) for i in range(4,len(pnames),8)]
    textures={}
    for tn in ('TEXTURE1','TEXTURE2'):
        if tn not in lumps:continue
        data=lump(tn);num=struct.unpack_from('<I',data)[0]
        for off in struct.unpack_from('<'+'I'*num,data,4):
            n,_,w,h,_,np=struct.unpack_from('<8sIhhIh',data,off)
            layers=[]
            for j in range(np):
                x,y,k,_,_=struct.unpack_from('<hhhhh',data,off+22+10*j)
                o,l=lumps[patches[k]];layers.append((x,y,o,l))
            textures[read_name(n)]=(w,h,layers)
    mats=[];ids={};layers=[]
    def material(n,kind):
        n=read_name(n) if isinstance(n,bytes) else n
        if n=='-':return -1
        if (kind,n) in ids:return ids[kind,n]
        if kind=='flat' and n=='F_SKY1':return material('SKY1','wall')
        if kind=='wall':w,h,parts=textures[n];flag=0
        elif kind=='patch':
            o,l=lumps[n];w,h=struct.unpack_from('<hh',wad,o);parts=[(0,0,o,l)];flag=0
        else:
            o,l=lumps[n];assert l==4096
            w=h=64;parts=[(0,0,o,l)];flag=1
        idx=len(mats);ids[kind,n]=idx
        mats.append((w,h,len(layers),len(parts),flag));layers.extend(parts);return idx
    # Convex subsector floors: intersect ancestor BSP half-planes and directed segs.
    def clip(poly,x,y,dx,dy,sign=1):
        out=[]
        def distance(p):return sign*(dy*(p[0]-x)-dx*(p[1]-y))
        for a,b in zip(poly,poly[1:]+poly[:1]):
            da,db=distance(a),distance(b)
            if da>=-1e-6:out.append(a)
            if (da>=-1e-6)!=(db>=-1e-6):
                t=da/(da-db);out.append((a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t))
        return out
    tris=[]
    # World z comes from an original sector floor or ceiling. UV coordinates in texels.
    def tri(mat,sec,verts):
        if mat<0:return
        tris.append((mat,sec,*[v for vertex in verts for v in vertex]))
    def visit(index,poly):
        if index<32768:
            x,y,dx,dy,*_=nodes[index]
            for side,child in enumerate(nodes[index][-2:]):
                visit(child,clip(poly,x,y,dx,dy,1 if side==0 else -1))
            return
        num,first=leaves[index&32767];group=segs[first:first+num]
        sec=sides[lines[group[0][3]][5+group[0][4]]][-1]
        for a,b,*_ in group:
            x,y=vertices[a];bx,by=vertices[b];poly=clip(poly,x,y,bx-x,by-y)
        for i in range(1,len(poly)-1):
            for ceiling in (0,1):
                mat=material(secs[sec][2+ceiling],'flat')
                tri(mat,sec,[(x,y,sec*2+ceiling,x,-y) for x,y in (poly[0],poly[i],poly[i+1])])
    visit(len(nodes)-1,[(-8192,-8192),(8192,-8192),(8192,8192),(-8192,8192)])
    # Both sides are generated. Floor/ceiling differences determine visible spans at runtime.
    for a,b,flags,special,tag,front,back in lines:
        for side,opposite,v1,v2 in ((front,back,a,b),(back,front,b,a)):
            if side==65535:continue
            xoff,yoff,upper,lower,middle,sec=sides[side];ax,ay=vertices[v1];bx,by=vertices[v2]
            length=math.hypot(bx-ax,by-ay);floor,ceil=sec*2,sec*2+1
            spans=[]
            if opposite==65535:spans=[(middle,floor,ceil, bool(flags&16))]
            else:
                other=sides[opposite][-1]
                if not (secs[sec][3]==secs[other][3]==b'F_SKY1\0\0'):
                    spans.append((upper,other*2+1,ceil,not bool(flags&8)))
                spans.append((lower,floor,other*2,bool(flags&16)))
                if read_name(middle)!='-':
                    bottom=max((floor,other*2),key=lambda k:secs[k//2][k%2])
                    top=min((ceil,other*2+1),key=lambda k:secs[k//2][k%2])
                    spans.append((middle,bottom,top,bool(flags&16)))
            for texture,lo,hi,peg_bottom in spans:
                mat=material(texture,'wall')
                if mat<0:continue
                # Negative anchor-encoding distinguishes wall UVs from flat UVs.
                anchor=(lo if peg_bottom else hi)
                # Encode linked height and vertical offset; renderer computes v from current z.
                code=(anchor+1)*8192+4096+yoff
                verts=[(ax,ay,lo,xoff,code),(bx,by,lo,xoff+length,code),(bx,by,hi,xoff+length,code),(ax,ay,hi,xoff,code)]
                tri(mat,sec,verts[:3]);tri(mat,sec,[verts[0],verts[2],verts[3]])
    things=records('5h','THINGS')
    names={2028:'COLUA0',2035:'BAR1A0',2015:'BON2A0',2014:'BON1A0',9:'SPOSA1',3004:'POSSA1',3001:'TROOA1',2049:'SBOXA0',2048:'AMMOA0',2012:'MEDIA0',2008:'SHELA0',2046:'BROKA0',48:'ELECA0',2007:'CLIPA0',35:'CBRAA0',2011:'STIMA0',2018:'ARM1A0',2001:'SHOTA0',24:'POL5A0',2019:'ARM2A0',2003:'LAUNA0',2002:'MGUNA0',10:'PLAYW0',12:'PLAYW0',15:'PLAYN0'}
    sprites=[]
    for x,y,angle,kind,flags in things:
        n=names.get(kind)
        if n in lumps and flags&2 and not flags&16:
            o,_=lumps[n];w,h,left,top=struct.unpack_from('<hhhh',wad,o)
            sprites.append((x,y,material(n,'patch'),left,top))
    gun=[material(n,'patch') for n in ('PISGA0','PISGB0','PISFA0','STBAR','STFST00')]
    digit_ids=[material('STTNUM'+str(i),'patch') for i in range(10)]
    digit_ids.append(material('STTPRCNT','patch'))
    digit_ids.extend(material('STYSNUM'+str(i),'patch') for i in range(10))
    # Runtime retains original map/sound references and decodes artwork from the IWAD.
    table_names=['VERTEXES','LINEDEFS','SIDEDEFS','SECTORS','SEGS','SSECTORS','NODES','THINGS','PLAYPAL','COLORMAP','DSPISTOL','DSDOROPN','DSSWTCHN','DSITEMUP']
    offsets=[v for n in table_names for v in (map_lumps if n in map_lumps else lumps)[n]]
    def group(rows,fmt):return b''.join(struct.pack('<'+fmt,*r) for r in rows)
    header=struct.pack('<4s32s4I28I5I',b'SYH1',hashlib.sha256(wad).digest(),len(mats),len(layers),len(tris),len(sprites),*offsets,*gun)
    stops = []
    for sec, sector in enumerate(secs):
        neighbors=[]
        for a,b,flags,special,tag,front,back in lines:
            if back==65535:continue
            f,r=sides[front][-1],sides[back][-1]
            if f==sec and r!=sec:neighbors.append(secs[r][1])
            if r==sec and f!=sec:neighbors.append(secs[f][1])
        stops.append(max(0, min(neighbors,default=sector[1])-4-sector[1]))
    return header+group(mats,'5i')+group(layers,'4i')+group(sorted(tris,key=lambda t:t[0]),'2i'+'ffi ff'.replace(' ','')*3)+group(sprites,'5i')+struct.pack('<85i21i',*stops,*digit_ids)

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('Usage: python3 import_iwad.py /path/to/doom1.wad')
    path=Path(sys.argv[1]);out=path.with_suffix('.syi');out.write_bytes(compile_index(path));print(out,out.stat().st_size)

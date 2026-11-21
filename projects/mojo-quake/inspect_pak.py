"""Inventory the selected Quake episode without copying its maps or art to the repository."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
from prepare_shareware import PAK_SHA


def pak_files(pak):
    contents = pak.read_bytes()
    if hashlib.sha256(contents).hexdigest() != PAK_SHA:
        raise ValueError("Expected the original Quake shareware 1.06 pak0.pak")
    magic, directory, size = struct.unpack_from("<4sII", contents)
    if magic != b"PACK" or size % 64 or directory + size > len(contents):
        raise ValueError("Invalid PAK directory")
    files = {}
    for raw, start, length in struct.iter_unpack("<56sII", contents[directory:directory+size]):
        name = raw.split(b"\0",1)[0].decode("ascii")
        if start + length > len(contents) or name in files:
            raise ValueError(f"Invalid PAK member {name}")
        files[name] = memoryview(contents)[start:start+length]
    return files


def add_engine_observations(files, result, logs):
    """Merge precache and builtin observations from native -mqinventory output."""
    models = {name: set() for name in result["maps"]}
    sounds = {name: set() for name in models}
    calls = {name: set() for name in models}
    for path in logs:
        for line in path.read_text().splitlines():
            if not line.startswith(("MQ_MODEL ", "MQ_SOUND ", "MQ_BUILTIN ")):
                continue
            kind, name, value = line.split(maxsplit=2)
            if name not in models:
                raise ValueError(f"Unexpected map {name} in {path.name}")
            if kind == "MQ_BUILTIN":
                number, function = value.split(maxsplit=1)
                if result["declared_builtins"].get(number) != function:
                    raise ValueError(f"Unexpected builtin {value} in {name}")
                calls[name].add(int(number))
            elif kind == "MQ_SOUND":
                if "sound/" + value not in files:
                    raise ValueError(f"Missing sound {value} for {name}")
                sounds[name].add(value)
            else:
                if not value.startswith("*") and value not in files:
                    raise ValueError(f"Missing model {value} for {name}")
                models[name].add(value)

    for name, info in result["maps"].items():
        if f"maps/{name}.bsp" not in models[name] or not sounds[name] or not calls[name]:
            raise ValueError(f"No complete engine observation for {name}")
        info["inline_brush_models"] = sum(model.startswith("*") for model in models[name])
        info["model_files"] = sorted(model for model in models[name] if not model.startswith("*"))
        info["sound_files"] = sorted("sound/" + sound for sound in sounds[name])
        info["observed_builtin_ids"] = sorted(calls[name])


def inventory(path, logs=()):
    files=pak_files(path)
    maps={}
    for name in ["start",*(f"e1m{i}" for i in range(1,9))]:
        bsp=files[f"maps/{name}.bsp"]
        version, *lumps=struct.unpack_from("<31i",bsp)
        if version!=29 or any(start<0 or length<0 or start+length>len(bsp) for start,length in zip(lumps[::2],lumps[1::2])):
            raise ValueError(f"Invalid BSP29 map {name}")
        data=bytes(bsp[lumps[0]:lumps[0]+lumps[1]]).strip(b"\0").decode("latin1")
        entities=[dict(re.findall(r'"([^"]+)"\s*"([^"]*)"',block)) for block in re.findall(r'\{([^{}]*)\}',data)]
        kinds=Counter(e.get("classname","") for e in entities)
        maps[name]={"entities":len(entities),"classes":dict(sorted(kinds.items())),
                    "destinations":sorted({e["map"] for e in entities if e.get("classname")=="trigger_changelevel" and "map" in e}),
                    "faces":lumps[15]//20,"clipnodes":lumps[19]//8,"lightmap_bytes":lumps[17]}
    code=files["progs.dat"];version,crc,_,statements,_,_,_,_,funcs,count,strings,slen,_,globals_count,entity_words=struct.unpack_from("<15i",code)
    table=bytes(code[strings:strings+slen]); builtins={}
    for i in range(count):
        entry,_,_,_,n,_,_,*_=struct.unpack_from("<7i8B",code,funcs+36*i)
        if entry<0:builtins[str(-entry)]=table[n:table.index(b"\0",n)].decode("ascii")
    result = {"pak_sha256":PAK_SHA,"progs_sha256":hashlib.sha256(code).hexdigest(),"vm_version":version,
            "system_crc":crc,"statements":statements,"functions":count,"global_words":globals_count,
            "entity_words":entity_words,"declared_builtins":builtins,"maps":maps}
    if logs:
        add_engine_observations(files, result, logs)
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pak",type=Path)
    parser.add_argument("--observations", nargs="+", type=Path, default=(),
                        help="native -mqinventory logs covering the hub and all eight maps")
    args=parser.parse_args()
    print(json.dumps(inventory(args.pak, args.observations),indent=2))

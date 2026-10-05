#!/usr/bin/env python3
"""Eva theme candidates with stable-diffusion.cpp + Z-Image-Turbo. usage: gen.py JOB... [--n 2] [--seed 1000]"""
import argparse, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
M = Path.home() / ".local/share/sdcpp/models"
SD = Path.home() / ".local/bin/sdcpp"

SIL = ("A solid pure black silhouette of {what} on a perfectly flat, solid white background. {pose} Full body, nothing "
       "cropped, feet on the ground. Flat vector silhouette art, no shading, no details inside the silhouette, no text, no border.")
UNIT01 = ("the giant humanoid mecha Evangelion Unit-01: slender tall humanoid robot body, a single long horn on the forehead, "
          "tall boxy shoulder pylons, narrow waist, long legs")
INK = ("Dark screen-printed ink illustration on a jet-black background: mostly black, drawn with fine pale lavender-white "
       "linework, cross-hatching and halftone dots, large areas filled with deep violet purple and one or two small accents of "
       "acid neon green. Moody, high contrast, lots of black negative space, manga and Neon Genesis Evangelion inspired. "
       "{frame} No text, no letters, no logos, no border, no frame.")
WIDE = INK.format(frame="Ultra-wide panoramic framing.")
TALL = INK.format(frame="Tall vertical portrait framing.")

JOBS = {
    # figures (silhouettes)
    "eva01_stance": (896, 1344, SIL.format(what=UNIT01, pose="Hunched aggressive fighting stance seen from the side facing left, fists clenched, feet planted apart.")),
    "eva01_berserk": (896, 1344, SIL.format(what=UNIT01, pose="Berserk: hunched forward, seen from the front in three-quarter view, jaw wide open roaring, arms spread low with clawed hands, legs wide.")),
    "eva01_knife": (896, 1344, SIL.format(what=UNIT01, pose="Standing tall seen from the side facing left, holding a large combat knife low in the right hand, left arm back, one foot forward.")),
    "eva01_tpose": (1152, 1152, SIL.format(what=UNIT01, pose="Standing straight and symmetrical, seen exactly from the front, both arms stretched straight out horizontally to the sides at shoulder height, open hands, legs slightly apart.")),
    "eva01_cross": (1152, 1152, SIL.format(what=UNIT01, pose="Crucified: nailed to a giant cross, seen exactly from the front, both arms stretched out straight and horizontal along the crossbeam at shoulder height, open hands, body hanging straight, legs together. The cross itself is white and invisible, only the robot is black.")),
    "eva01_arms_up": (1152, 1152, SIL.format(what=UNIT01, pose="Seen exactly from the front, both arms raised high and wide above its head in a V shape, open hands reaching to the sky, head tilted back roaring, legs apart.")),
    "eva01_tall": (768, 1792, SIL.format(what=UNIT01, pose="Standing tall and upright seen from the front, arms at the sides, looking up, feet apart.")),
    # ultrawide wallpapers
    "wp_unit01_moon": (1792, 768, "A close-up of the head of Evangelion Unit-01 in profile, long horn, jaw open roaring, a huge full moon behind it. " + WIDE),
    "wp_unit01_hill": (1792, 768, "The giant mecha Evangelion Unit-01 standing on a hilltop at night, seen from far away as a dark silhouette with its horn and shoulder pylons, a colossal moon filling the sky behind it, a ruined city below. " + WIDE),
    "wp_lilith": (1792, 768, "A colossal pale white giant with a seven-eyed purple mask, nailed to a huge black cross in a vast dark cavern, its legs dissolved into a lake of glowing liquid, tiny catwalks and spotlights in the distance. " + WIDE),
    "wp_tokyo3": (1792, 768, "A futuristic city of skyscrapers in a wide valley at dusk, a giant glowing blue octahedron crystal floating in the sky above it, a drill beam of light shooting down from the crystal into the city, mountains behind. " + WIDE),
    "wp_cross": (1792, 768, "A gigantic cross-shaped pillar of blinding light rising from a city on the sea at the horizon, shockwave rings of dust, a lone giant humanoid mecha silhouette in the foreground. " + WIDE),
    "wp_sachiel": (1792, 768, "A tall thin humanoid angel with a bird-skull bone mask for a face and a glowing red sphere core in its chest, walking slowly through a city of skyscrapers, military helicopters around it, seen from below. " + WIDE),
    "wp_lance": (1792, 768, "A giant red double-helix lance spiralling up into the night sky towards the moon, leaving a trail of light, seen from the ground past a ruined cityscape. " + WIDE),
    "wp_atfield": (1792, 768, "A giant hexagonal honeycomb energy barrier glowing in the air, rippling outward from the clenched fist of a giant mecha pressing against it, hexagons fading into darkness. " + WIDE),
    "wp_train": (1792, 768, "The empty interior of a commuter train at sunset, long rows of seats and hanging hand straps, harsh sunlight through the windows, one lone figure sitting alone at the far end. " + WIDE),
    "wp_geofront": (1792, 768, "An enormous underground cavern with a lake and forests, a huge inverted black pyramid headquarters building standing on the lake, a city hanging from the cavern ceiling upside down, shafts of light from above. " + WIDE),
    "wp_plug": (1792, 768, "The inside of a cylindrical cockpit capsule, a pilot's seat with twin control grips, the curved walls glowing with floating holographic readouts, the whole chamber filled with amber liquid. " + WIDE),
    # portrait side monitor
    "pt_unit01": (768, 1792, "The giant mecha Evangelion Unit-01 standing tall at night, seen from below, its horn and shoulder pylons against a colossal moon, ruined buildings at its feet. " + TALL),
    "pt_sachiel": (768, 1792, "A tall thin humanoid angel with a bird-skull bone mask for a face and a glowing red sphere core in its chest, standing between skyscrapers, seen from below. " + TALL),
    "pt_lilith": (768, 1792, "A colossal pale white giant with a seven-eyed purple mask nailed to a huge black cross in a dark cavern, seen from below, its legs dissolved into a glowing lake. " + TALL),
}


def run(job, n, seed, steps):
    w, h, prompt = JOBS[job]
    todo = [s for s in range(seed, seed + n) if not (RAW / f"{job}_{s}.png").exists()]
    if not todo:
        return
    RAW.mkdir(exist_ok=True)
    tmp = RAW / f".{job}_%d.png"
    start, count = todo[0], todo[-1] - todo[0] + 1
    cmd = [str(SD), "--diffusion-model", str(M / "z_image_turbo-Q6_K.gguf"), "--vae", str(M / "ae.safetensors"),
           "--llm", str(M / "Qwen3-4B-Q8_0.gguf"), "-p", prompt, "--cfg-scale", "1.0", "--steps", str(steps),
           "-W", str(w), "-H", str(h), "-s", str(start), "-b", str(count), "-o", str(tmp), "--offload-to-cpu", "--diffusion-fa"]
    t = time.time()
    p = subprocess.run(["nice", "-n", "10"] + cmd, capture_output=True, text=True)
    if p.returncode:
        sys.stderr.write(p.stdout[-3000:] + p.stderr[-3000:])
        raise SystemExit(f"{job}: sd-cli failed ({p.returncode})")
    made = sorted(RAW.glob(f".{job}_*.png"), key=lambda q: int(q.stem.rsplit("_", 1)[1]))
    for i, f in enumerate(made):
        f.rename(RAW / f"{job}_{start + i}.png")
    print(f"{job}: {len(made)} image(s) in {time.time() - t:.0f}s", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs", nargs="+")
    ap.add_argument("--n", type=int, default=2)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--steps", type=int, default=8)
    a = ap.parse_args()
    jobs = list(JOBS) if a.jobs == ["all"] else a.jobs
    for j in jobs:
        run(j, a.n, a.seed, a.steps)

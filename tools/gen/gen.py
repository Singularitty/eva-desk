#!/usr/bin/env python3
"""Batch-generate figure candidates with stable-diffusion.cpp + Z-Image-Turbo.

usage: gen.py JOB [JOB...] [--n 4] [--seed 1000] [--steps 8]
Writes raw/<job>_<seed>.png and skips seeds that already exist.
"""
import argparse, os, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
M = Path.home() / ".local/share/sdcpp/models"
SD = Path.home() / ".local/bin/sdcpp"

GREEN = ("The chroma-key green screen behind him is lit separately and evenly: a perfectly flat, solid "
         "green background, no props, no text, no border.")

RIM = ("Low-key lighting: he is lit only from behind by two hard {col} rim lights, so his body is mostly "
       "deep black shadow and a thin bright edge of light traces the outline of every muscle.")

HERALD = ("Full-body backlit photograph of a tall, ripped warrior seen straight from the front, standing "
          "with his feet planted apart, {pose}. Bare-chested with a sculpted, deeply defined chest, abs, "
          "shoulders and arms, loose dark trousers and boots, a long tattered cape hanging from his "
          "shoulders behind him. " + RIM.format(col="golden") + " " + GREEN)

JOBS = {
    "boxer_back": (896, 1344, (
        "Full-body backlit photograph of a ripped heavyweight boxer seen directly from behind, standing "
        "tall with both arms raised in victory, upper arms horizontal and forearms pointing straight up "
        "like a goalpost, black boxing gloves high above his head. Bodybuilder physique with an extremely "
        "shredded back: huge flared lats, thick trapezius, round striated rear deltoids, bulging triceps, "
        "a deep spinal groove, visible separation between every muscle. Black satin boxing trunks and "
        "black boxing boots. " + RIM.format(col="white") + " " + GREEN)),
    "boxer_guard": (896, 1344, (
        "Full-body backlit photograph of a ripped boxer in a fighting stance seen from the side, facing "
        "left, lead fist raised high in front of his face and rear glove tucked by his chin, left foot "
        "forward. Bodybuilder physique, shredded shoulders, arms and back, black boxing gloves, black "
        "trunks and boots. " + RIM.format(col="white") + " " + GREEN)),
    "herald_1": (1152, 1152, HERALD.format(pose="both arms hanging relaxed at his sides with open hands")),
    "herald_2": (1152, 1152, HERALD.format(pose="both arms stretched straight out to the sides at shoulder height, palms open facing forward")),
    "herald_3": (1152, 1152, HERALD.format(pose="both arms raised high and wide above his head in a V shape, palms open toward the sky, praising the sun")),
    "herald_tri": (2048, 1024, (
        "Three photographs side by side of the same tall, ripped warrior on the same green screen, seen "
        "straight from the front, full body, feet planted apart, identical in every way except his arms. "
        "Left panel: arms hanging relaxed at his sides. Middle panel: arms stretched straight out to the "
        "sides at shoulder height, palms open. Right panel: arms raised high and wide in a V, palms open "
        "toward the sky, praising the sun. Bare-chested with a sculpted, deeply defined chest, abs and "
        "arms, loose dark trousers and boots, a long tattered cape behind him. Low-key lighting: lit only "
        "from behind by two hard golden rim lights, so his body is mostly deep black shadow with a thin "
        "bright edge of light along every muscle. Each panel has the same evenly lit, perfectly flat, solid "
        "chroma-key green background, no text, no borders between panels.")),
    "wp_sun": (1792, 768, ("A colossal sun drawn as concentric rings of crimson and off-white, filled with coarse halftone dots, half-sunk behind a jagged black mountain ridge, a few long thin black clouds across it, no rays. "
        "Flat screen-printed poster illustration in exactly three inks: jet black, warm off-white paper and deep crimson red. "
        "Bold graphic silhouette art with heavy solid black shapes, crisp hand-inked edges, coarse halftone dot shading in red "
        "and black, dramatic high-contrast composition in the style of Persona 5 key art and vintage propaganda posters. "
        "Ultra-wide panoramic framing. No text, no letters, no logos, no border, no frame.")),
    "wp_emperor": (1792, 768, ("An emperor in profile with eyes closed, wearing an enormous spiked sun crown and a feathered headdress, before a giant sun on the horizon. "
        "Flat screen-printed poster illustration in exactly three inks: jet black, warm off-white paper and deep crimson red. "
        "Bold graphic silhouette art with heavy solid black shapes, crisp hand-inked edges, coarse halftone dot shading in red "
        "and black, dramatic high-contrast composition in the style of Persona 5 key art and vintage propaganda posters. "
        "Ultra-wide panoramic framing. No text, no letters, no logos, no border, no frame.")),
    "wp_crt": (1792, 768, ("A retro 1980s home computer with a chunky CRT monitor, keyboard and floppy disks on a desk, the screen glowing with scanlines, tangled cables. "
        "Flat screen-printed poster illustration in exactly three inks: jet black, warm off-white paper and deep crimson red. "
        "Bold graphic silhouette art with heavy solid black shapes, crisp hand-inked edges, coarse halftone dot shading in red "
        "and black, dramatic high-contrast composition in the style of Persona 5 key art and vintage propaganda posters. "
        "Ultra-wide panoramic framing. No text, no letters, no logos, no border, no frame.")),
    "wp_helmets": (1792, 768, ("Two sleek robot helmets with dark visors floating side by side in front of a glowing pyramid made of light beams. "
        "Flat screen-printed poster illustration in exactly three inks: jet black, warm off-white paper and deep crimson red. "
        "Bold graphic silhouette art with heavy solid black shapes, crisp hand-inked edges, coarse halftone dot shading in red "
        "and black, dramatic high-contrast composition in the style of Persona 5 key art and vintage propaganda posters. "
        "Ultra-wide panoramic framing. No text, no letters, no logos, no border, no frame.")),
    "wp_wine": (1792, 768, ("A tall wine bottle pouring into a crystal wine glass, the wine splashing upward into a crown shape, grapes and vine leaves around it. "
        "Flat screen-printed poster illustration in exactly three inks: jet black, warm off-white paper and deep crimson red. "
        "Bold graphic silhouette art with heavy solid black shapes, crisp hand-inked edges, coarse halftone dot shading in red "
        "and black, dramatic high-contrast composition in the style of Persona 5 key art and vintage propaganda posters. "
        "Ultra-wide panoramic framing. No text, no letters, no logos, no border, no frame.")),
    "wp_gloves": (1792, 768, ("A pair of boxing gloves hanging by their laces from a ring post, the ring ropes stretching across the frame under harsh spotlights. "
        "Flat screen-printed poster illustration in exactly three inks: jet black, warm off-white paper and deep crimson red. "
        "Bold graphic silhouette art with heavy solid black shapes, crisp hand-inked edges, coarse halftone dot shading in red "
        "and black, dramatic high-contrast composition in the style of Persona 5 key art and vintage propaganda posters. "
        "Ultra-wide panoramic framing. No text, no letters, no logos, no border, no frame.")),
    "wp_sword": (1792, 768, ("A long sword plunged into a rock in the foreground, a gothic castle on a cliff behind it under a giant full moon, crows circling. "
        "Flat screen-printed poster illustration in exactly three inks: jet black, warm off-white paper and deep crimson red. "
        "Bold graphic silhouette art with heavy solid black shapes, crisp hand-inked edges, coarse halftone dot shading in red "
        "and black, dramatic high-contrast composition in the style of Persona 5 key art and vintage propaganda posters. "
        "Ultra-wide panoramic framing. No text, no letters, no logos, no border, no frame.")),
    "wp_city": (1792, 768, ("A lone figure standing on a rooftop above a dense city skyline at night, a huge moon, telephone wires and antennas. "
        "Flat screen-printed poster illustration in exactly three inks: jet black, warm off-white paper and deep crimson red. "
        "Bold graphic silhouette art with heavy solid black shapes, crisp hand-inked edges, coarse halftone dot shading in red "
        "and black, dramatic high-contrast composition in the style of Persona 5 key art and vintage propaganda posters. "
        "Ultra-wide panoramic framing. No text, no letters, no logos, no border, no frame.")),
    "dk_ring": (1792, 768, ("An empty boxing ring in a dark arena at night, lit by a single spotlight cone from above, a pair of boxing gloves hanging from the top rope. "
        "Dark screen-printed ink illustration on a jet-black background: mostly black, drawn with fine warm off-white "
        "linework, cross-hatching and halftone dots, with only one or two small accents of deep crimson red. Moody, high "
        "contrast, lots of black negative space, manga and Persona 5 inspired. Ultra-wide panoramic framing. No text, no "
        "letters, no logos, no border, no frame.")),
    "dk_sword": (1792, 768, ("A long sword planted in a rocky hill in the foreground, a distant gothic castle on a cliff under a pale full moon, crows circling. "
        "Dark screen-printed ink illustration on a jet-black background: mostly black, drawn with fine warm off-white "
        "linework, cross-hatching and halftone dots, with only one or two small accents of deep crimson red. Moody, high "
        "contrast, lots of black negative space, manga and Persona 5 inspired. Ultra-wide panoramic framing. No text, no "
        "letters, no logos, no border, no frame.")),
    "dk_eclipse": (1792, 768, ("A total solar eclipse: a black sun with a thin glowing off-white corona ring, above a jagged mountain ridge at night. "
        "Dark screen-printed ink illustration on a jet-black background: mostly black, drawn with fine warm off-white "
        "linework, cross-hatching and halftone dots, with only one or two small accents of deep crimson red. Moody, high "
        "contrast, lots of black negative space, manga and Persona 5 inspired. Ultra-wide panoramic framing. No text, no "
        "letters, no logos, no border, no frame.")),
    "dk_emperor": (1792, 768, ("An emperor in profile with closed eyes, wearing an enormous spiked crown, a thin glowing ring behind his head. "
        "Dark screen-printed ink illustration on a jet-black background: mostly black, drawn with fine warm off-white "
        "linework, cross-hatching and halftone dots, with only one or two small accents of deep crimson red. Moody, high "
        "contrast, lots of black negative space, manga and Persona 5 inspired. Ultra-wide panoramic framing. No text, no "
        "letters, no logos, no border, no frame.")),
    "dk_crt": (1792, 768, ("A retro 1980s computer with a chunky CRT monitor glowing in a pitch-dark room, the screen is the only light, cables snaking across the desk. "
        "Dark screen-printed ink illustration on a jet-black background: mostly black, drawn with fine warm off-white "
        "linework, cross-hatching and halftone dots, with only one or two small accents of deep crimson red. Moody, high "
        "contrast, lots of black negative space, manga and Persona 5 inspired. Ultra-wide panoramic framing. No text, no "
        "letters, no logos, no border, no frame.")),
    "dk_helmets": (1792, 768, ("Two sleek robot helmets with dark visors facing each other in darkness, thin lines of light reflecting on their chrome. "
        "Dark screen-printed ink illustration on a jet-black background: mostly black, drawn with fine warm off-white "
        "linework, cross-hatching and halftone dots, with only one or two small accents of deep crimson red. Moody, high "
        "contrast, lots of black negative space, manga and Persona 5 inspired. Ultra-wide panoramic framing. No text, no "
        "letters, no logos, no border, no frame.")),
    "dk_wine": (1792, 768, ("A wine glass and a bottle on a dark table, a single drop of wine falling into the glass, candle smoke curling upward. "
        "Dark screen-printed ink illustration on a jet-black background: mostly black, drawn with fine warm off-white "
        "linework, cross-hatching and halftone dots, with only one or two small accents of deep crimson red. Moody, high "
        "contrast, lots of black negative space, manga and Persona 5 inspired. Ultra-wide panoramic framing. No text, no "
        "letters, no logos, no border, no frame.")),
    "dk_city": (1792, 768, ("A lone figure on a rooftop above a dark sleeping city, a huge pale moon, telephone wires and antennas. "
        "Dark screen-printed ink illustration on a jet-black background: mostly black, drawn with fine warm off-white "
        "linework, cross-hatching and halftone dots, with only one or two small accents of deep crimson red. Moody, high "
        "contrast, lots of black negative space, manga and Persona 5 inspired. Ultra-wide panoramic framing. No text, no "
        "letters, no logos, no border, no frame.")),
    "castle_a": (1792, 768, (
        "Wide cinematic dark fantasy matte painting at dusk. The pitch-black silhouette of a ruined gothic "
        "castle with tall broken spires stands on a distant hill on the right, against an enormous "
        "smouldering sky that glows blood red overhead and ember orange near the horizon. Glowing embers "
        "and ash drift through the air, a low mist fills the valley, the foreground is a dark rocky slope. "
        "Only black silhouettes against the glowing sky, high contrast, no people, no text, no border.")),
    "castle_b": (1792, 768, (
        "Wide cinematic dark fantasy matte painting. An enormous black fortress with sharp towers and a "
        "crumbling bridge rises from a jagged cliff on the right, a huge pale blood-red moon low behind it, "
        "thick red haze, glowing embers and ash in the air. Pure black silhouettes against the glowing red "
        "sky, high contrast, minimalist, no people, no text, no border.")),
    "knight2": (1216, 1024, (
        "Full-body backlit photograph of an exhausted knight in full dark plate armour seen from the "
        "side, sitting on the floor and leaning his back against a wall on the left, facing right. One "
        "knee is drawn up, the other leg stretched out, his helmeted head bowed. A long sword is planted "
        "point-down beside him and both gauntlets rest on its crossguard. Heavy pauldrons, a torn cloak. "
        "He sits inside a seamless chroma-key green infinity cove: the floor, the wall behind his back and "
        "the background are one continuous, bright, evenly lit green surface with no visible corner and no "
        "shadows. Low-key lighting on the knight himself: only a dim red rim light from behind catches the "
        "edges of his armour, and a thin red glow shows through the visor slit. No props, no text, no border.")),
    "knight": (1216, 1024, (
        "Full-body backlit photograph of an exhausted knight in full dark plate armour seen from the "
        "side, sitting on the ground and leaning his back against a plain wall on the left, facing right. "
        "One knee is drawn up, the other leg stretched out, his helmeted head bowed. A long sword is "
        "planted point-down in the ground beside him and both gauntlets rest on its crossguard. Heavy "
        "pauldrons, a torn cloak pooling on the ground. Low-key lighting: only a dim red rim light from "
        "behind catches the edges of the armour, and a thin red glow shows through the visor slit. The "
        "wall and the background are the same evenly lit, perfectly flat, solid chroma-key green, no "
        "props, no text, no border.")),
}


def run(job, n, seed, steps):
    w, h, prompt = JOBS[job]
    todo = [s for s in range(seed, seed + n) if not (RAW / f"{job}_{s}.png").exists()]
    if not todo:
        return
    RAW.mkdir(exist_ok=True)
    tmp = RAW / f".{job}_%d.png"
    start = todo[0]
    count = todo[-1] - start + 1
    cmd = [str(SD), "--diffusion-model", str(M / "z_image_turbo-Q6_K.gguf"), "--vae", str(M / "ae.safetensors"),
           "--llm", str(M / "Qwen3-4B-Q8_0.gguf"), "-p", prompt, "--cfg-scale", "1.0", "--steps", str(steps),
           "-W", str(w), "-H", str(h), "-s", str(start), "-b", str(count), "-o", str(tmp),
           "--offload-to-cpu", "--diffusion-fa"]
    t = time.time()
    p = subprocess.run(["nice", "-n", "10"] + cmd, capture_output=True, text=True)
    if p.returncode:
        sys.stderr.write(p.stdout[-3000:] + p.stderr[-3000:])
        raise SystemExit(f"{job}: sd-cli failed ({p.returncode})")
    # sd-cli numbers batch images from 1 when -o has %d; map them back to their seeds
    made = sorted(RAW.glob(f".{job}_*.png"), key=lambda q: int(q.stem.rsplit("_", 1)[1]))
    for i, f in enumerate(made):
        f.rename(RAW / f"{job}_{start + i}.png")
    print(f"{job}: {len(made)} image(s) in {time.time() - t:.0f}s", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs", nargs="+")
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--steps", type=int, default=8)
    a = ap.parse_args()
    for j in a.jobs:
        run(j, a.n, a.seed, a.steps)

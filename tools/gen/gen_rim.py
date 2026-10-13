#!/usr/bin/env python3
"""Unit-01 lit from behind, on black: the pictures of the standby loop. usage: gen_rim.py [JOB...] [--n 4] [--seed 5000]

The figure is almost lost in black. A thin white rim light draws its shape, a little dark detail shows inside,
the eyes glow, and nothing else is in the frame. Make several seeds of each, choose, then run prep_art.py on
the ones you keep.
"""
import argparse

import gen

U = ("the giant humanoid mecha Evangelion Unit-01, a slender armoured humanoid robot with a single long sharp horn rising "
     "from the forehead of its helmet, a heavy armoured jaw, tall boxy shoulder pylons, a narrow waist and long limbs")
RIM = ("A minimalist dark anime illustration on a pure black background. {shot} The figure is almost completely swallowed by "
       "black shadow and melts into the black background: only a thin, crisp, bright white rim light traces the edge of its "
       "silhouette from behind, with a few fine white highlight lines along the edges of the armour. Inside the shadow the "
       "armour plates are just barely visible as very dark violet shapes. {eyes} glowing intense acid neon green, the only "
       "colour in the image, with a soft green glow. Everything else in the frame is flat, empty, pure black negative space. "
       "Low-key lighting, very high contrast, ominous and quiet. Clean anime line art, no smoke, no fog, no stars, no text, "
       "no letters, no logos, no border, no frame.")
SHOTS = {
    "r_bust": (1792, 768, f"An extreme close-up of the head and shoulders of {U}, seen in exact side profile facing left with its head bowed "
               "slightly forward. The bust sits on the right half of the ultra-wide frame and is cropped at the chest by the bottom edge.",
               "Its one visible eye is a narrow slit"),
    "r_front": (1792, 768, f"A close-up of the face of {U}, seen exactly from the front and looking straight at the viewer with its head lowered "
                "menacingly, the shoulder pylons rising on both sides of the head. The head sits in the centre of the ultra-wide frame "
                "and is cropped at the shoulders by the bottom edge.", "Its two narrow eyes are"),
    "r_full": (896, 1344, f"The whole body of {U} from the tip of its horn down to its feet, standing hunched forward in a three-quarter view "
               "facing left, long arms hanging with clenched fists, feet planted apart.", "Its narrow eyes are"),
}
gen.JOBS.update({job: (w, h, RIM.format(shot=shot, eyes=eyes)) for job, (w, h, shot, eyes) in SHOTS.items()})

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs", nargs="*")
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--seed", type=int, default=5000)
    a = ap.parse_args()
    for j in a.jobs or list(SHOTS):
        gen.run(j, a.n, a.seed, 8)

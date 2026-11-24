# Birdfy clip scoring protocol (batch 2026-11-05 to 2026-11-11)

This protocol continues the coding rules used in the earlier `birdfy_rows_*.xlsx` batches and adds the side-time columns David asked for on 2026-11-12.

## Inputs

- Clips: `raw_clips/YYYY-MM-DD_HHMMSS.mp4`. They are 2304x1296 at 15 fps, up to about 30 s long. The name gives the clip start time (America/New_York).
- `manifest.csv` maps each file to its Birdfy card time and Birdfy label.
- Frame sheets: `/usr/local/bin/python3 -I scripts/sheet.py CLIP OUT.jpg --start S --end E --fps F --cols C --width W [--crop x,y,w,h]`. Each frame is stamped with its time, and a cyan tick at the bottom marks the image centre. Write sheets under `sheets/<date>/`. View them with the Read tool.

## Feeder sides (most important rule)

- The camera faces the bird, so the sides are mirrored. The **image-left** tray is **feeder RIGHT**, and the **image-right** tray is **feeder LEFT**.
- The boundary between the trays is the **image centre, x = 1152** of 2304 (the cyan tick). Earlier batches found the seed type changes near x = 1150. The divider itself is usually not visible.
- In the spreadsheet, Left* columns mean feeder left (image-right) and Right* columns mean feeder right (image-left).

## Who gets a row

- One row per individual animal per clip. If two birds are on the feeder at once, give each its own row (`individual` 1, 2, ...) and track each one separately.
- Write clips with no animal (person only, owner refilling, empty, wind, insect) as one row with `individual` 0 and a short note. These do not become data rows. Describe people only as "person" or "owner" and what they do at the feeder, with nothing more about them.
- Species: identify from field marks and give them in the notes. The Birdfy label is only a hint and is often wrong. "Animals" usually means Eastern Gray Squirrel. Use `sex_if_known` only when it is clear (for example a male or female cardinal).

## Pecks (same as earlier batches)

- A peck is the bill striking into a tray. Count it on the side where the bill lands: image-left is feeder right, image-right is feeder left.
- Seed handling, cracking, chewing and holding are not pecks. Neither are head turns, looking down without contact, or the bill resting on the rail.
- Pecks are **blank for squirrels** (and other mammals), always.
- Fast blurred bouts (wrens, chickadees, woodpeckers): give your best count and a range in `peck_range`.
- Method: run a 4 fps pass over the whole clip. For each head-down moment, check 15 fps at higher zoom, using `--fps 15` over that short window and `--crop` on the trays if needed. Record `peck_times_s`, separated by semicolons.
- `confidence`: high, medium or low. Explain anything low in `notes`.

## Side time (NEW)

David's rule is that **time on a side goes by where the head is**.

- Sample the whole clip at **4 fps**, so each frame stands for 0.25 s. For each individual and each frame in which it is on the feeder (perched on the rim, standing in a tray, or clinging to it), look at the head's horizontal position:
  - head centre left of x = 1152 (image-left): add 0.25 s to `right_time_s` (feeder right)
  - head centre right of x = 1152 (image-right): add 0.25 s to `left_time_s` (feeder left)
- Frames where the animal is on the feeder but the head is hidden (behind the body, past the frame edge, or the lens is blocked): **best guess** the side from body position and posture, add it to that side, and also add 0.25 s to `guessed_time_s`. Say what was guessed in `time_note`.
- Head right on the centre line (within about 5% of frame width): best guess, and count it in `guessed_time_s`.
- Do not count time arriving or leaving in flight, or time the animal is fully out of frame. Mammals (squirrels) get side time too.
- `time_censored`: put `start` if the animal is already on the feeder in the first frame, `end` if it is still there in the last frame, `both` if both, and leave it blank otherwise. Clips stop at about 30 s, so censored times are lower bounds.
- Check: for each individual, left_time_s + right_time_s must equal the number of on-feeder frames x 0.25.

## Seed check

- In `seed_check`, record what is visible in each tray, using feeder-side words (for example "feeder left (image-right): peanuts, black sunflower; feeder right (image-left): striped/tan seed, mealworms"). Also note refills or empty trays. The last batch had LeftSeed "Peanuts, Sunflower" and RightSeed "Safflower, Mealworm". Flag anything that looks different.

## Output

Write `scores/scores_YYYY-MM-DD.csv` with Python's `csv` module (so quoting is correct) and these columns, in this order:

`file, individual, species, sex_if_known, left_pecks, right_pecks, peck_range, confidence, peck_times_s, left_time_s, right_time_s, guessed_time_s, time_censored, time_note, seed_check, notes, birdfy_label`

- One row per individual, or a single `individual` 0 row for a clip with no animal. Every clip in that day's manifest must appear.
- Notes follow the earlier style: say what happens and when, and explain why pecks were or weren't counted. Keep them factual, without padding.
- Save progress after each clip, appending rows, so the work can resume. Before starting a clip, skip any that already have rows.

## Additions after the first batch's blind check (2026-11-15)

- **Peck bouts:** a bout where the head stays down and works the seed counts as one peck per distinct strike, meaning the bill leaves the seed and goes back in. Do not split one continuous dig into a peck for every frame of movement. The largest blind-check disagreement (16 pecks against 5) came from splitting bouts in one scoring and missing them in the other. When unsure, give the middle count and a range.
- **The cyan line** on every sheet, including cropped zooms, marks the true side boundary at x = 1152. Use it for both pecks and side time.
- **Seeds:** the small striped/tan seed in the feeder-right (image-left) tray is the **safflower**. That is what it looks like on this camera. Do not report "no safflower seen". Note only real changes, such as refills, empty trays or mealworms appearing or running out.
- **Helper scripts:** give any helper scripts a name specific to your day, such as `scripts/d1112_*.py`. Shared names were overwritten by other agents in the first batch.

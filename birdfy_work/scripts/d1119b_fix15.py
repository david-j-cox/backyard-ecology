"""d1119b: apply 15 fps peck recounts for the dusk cardinal clips; other rows untouched."""
import csv
P = "/Users/davidjcox/Documents/campus-worktrees/6c828482/birdfy_work/scores/parts/scores_2026-11-19_b.csv"
U = {
 "2026-11-19_172710.mp4": ("3.37;7.5;11.88;17.37;23.75;25.68", "6-8", "medium",
  "Female Northern Cardinal (probably the same bird as 17:25; buff-brown with reddish wings and tail, orange bill) on the image-left near rim for the whole clip, side-on facing left. A full 7.5 fps scan found six head-down dips into the image-left tray; 15 fps zooms (cropped on the tray) show each is a single dip-and-lift, counted as one strike each at 3.37, 7.5, 11.88, 17.37, 23.75 and 25.68 s. The bill is blurred at the bottom of each dip, so a quick second strike could be hidden, hence the range. Between dips it sits cracking seed, facing the camera at 12.25-12.5, 24.0 and 26.0-26.25 s. Still on feeder at end."),
 "2026-11-19_173342.mp4": ("2.48;7.9;8.84;13.6;22.24;26.17;26.37", "6-8", "medium",
  "Male Northern Cardinal (all red, black face, red crest) on the image-left near rim for the whole clip, side-on facing left. 7.5 fps scan plus 15 fps zooms (cropped on the image-left tray): single-strike dips at 2.48, 7.9, 8.84, 13.6 and 22.24 s, and a dip at 26.1-26.4 s where the bill strikes at 26.17 s, lifts, and goes back in at 26.37 s (two strikes). A slight lean at 29.4 s does not reach the seed and is not counted. Sits cracking seed between dips. Still on feeder at end."),
 "2026-11-19_173906.mp4": ("1.15;1.32;6.37;11.43;17.93;22.8;27.13", "6-8", "medium",
  "Male Northern Cardinal (probably the same bird as 17:33) on the image-left near rim for the whole clip, mostly side-on facing left. 7.5 fps scan plus 15 fps zooms (cropped on the image-left tray): a two-strike dip at 1.1-1.37 s (strikes at 1.15 and 1.32 s with a partial lift between), then single-strike dips at 6.37 (bill clearly in the seed), 11.43, 17.93, 22.8 and 27.13 s. The blurred moments at 3.6-4.1 and 5.3 s are wing flicks and tail fanning, not dips. Sits cracking seed between dips. Still on feeder at end."),
 "2026-11-19_174232.mp4": ("2.93;7.55;12.2;17.75;17.95;18.93;24.7;29.47", "7-10", "medium",
  "Northern Cardinal (crest, heavy conical bill, long tail; sex not judged because the infrared image is greyscale) on the image-left near rim for the whole clip, side-on facing left, with frequent wing and tail flicks (0.25, 1.5, 2.25, 3.75, 5.25, 10.25, 15.36, 22.75 s; not dips). 7.5 fps scan plus 15 fps zooms (cropped on the image-left tray): single-strike dips at 2.93, 7.55, 12.2, 18.93, 24.7 and 29.47 s, and a longer bout at 17.68-18.43 s with strikes at 17.75 and 17.95 s (partial lift between) followed by a continuous dig counted as part of the second strike. Infrared makes the bill visible, but a further strike inside the 17.7-18.4 s bout is possible, hence the range. Still on feeder at end."),
 "2026-11-19_174403.mp4": ("3.95;11.17;15.2;19.4;19.65", "5-7", "medium",
  "One female Northern Cardinal (brown-buff body, reddish wings and tail, orange-red bill seen at 4.25 and 14.5 s), though Birdfy listed two. On the image-left near rim for the whole clip, side-on facing left. 7.5 fps scan plus 15 fps zooms (cropped on the image-left tray): single-strike dips at 3.95, 11.17 and 15.2 s, and a two-strike dip at 19.27-19.8 s (19.4 and 19.65 s, with the head lifting between). The earlier count's 26.1 s dip, and blurs at 22.3 and 23.3-23.6 s, are wing and tail flicks, not dips. Dim light, hence the range. Bluish smears right of centre at 12.0, 22.25-22.5 and 24.5-24.75 s are motion blur from its own wings and tail, not a second bird. Still on feeder at end."),
}
rows = list(csv.DictReader(open(P, newline="")))
cols = list(rows[0].keys()); before = {}
for r in rows:
    if r["file"] in U:
        before[r["file"]] = (r["right_pecks"], r["peck_times_s"])
        t, rg, cf, nt = U[r["file"]]
        r["left_pecks"] = "0"; r["right_pecks"] = str(len(t.split(";")))
        r["peck_times_s"], r["peck_range"], r["confidence"], r["notes"] = t, rg, cf, nt
assert len(before) == 5
with open(P, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
for k, (n, t) in before.items():
    print(k, "before", n, t, "| after", len(U[k][0].split(";")), U[k][0])

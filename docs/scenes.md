# What each scene asked for

Each scene ran with three fixed seeds, and the prompts were frozen before the first render. H3 runs at 24 frames a second,
so 141 frames is 5.9 seconds. Prompts follow the author's six-section format. The text itself is not in this repo: most of
it is the author's, and [their repository](https://github.com/yuanyang749/colab-ultra-workstation) has no license.

| Scene | Clips | Seeds | What the scene asks for |
|---|---|---|---|
| Monologue close-up | 1 x 141 frames | 2026110011 to 13 | One calm line in a tight, locked close-up |
| Two-person dialogue | 1 x 141 | 2026110021 to 23 | A static medium two-shot with one speaker and one silent listener |
| Over-the-shoulder pair | 2 x 141 | 2026110031 to 33 | Two separate clips, one from each side, that cut together with characters on the same sides |
| Walk and talk | 1 x 192 | 2026110041 to 43 | One unbroken tracking shot along a corridor while speaking |
| Emotional outburst | 1 x 141 | 2026110051 to 53 | A shouted line with a push-in and a slight shake at a slam on the table, then a settle |
| Stand up, camera follows | 1 x 141 | 2026110061 to 63 | A seated character stands and speaks while the camera moves to keep the head in frame |
| Reaction close-up | 1 x 90 | 2026110071 to 73 | A short startled line in a held close-up |
| Fight | 2 x 192, joined | 2026110081 to 83 | Two clips of choreographed exchanges, the second continuing from the first, with no blood or injury detail |
| Solo dance | 1 x 294 | 2026110091 to 93 | A contemporary dance phrase to music, full body in frame, from one portrait |
| Pouring tea | 1 x 192 | 2026110101 to 103 | One hand pours while the other stays flat, then the hands change roles at 6.5 s |
| Four-segment scene | 4 clips, about 20 s | Three seed sets starting 2026102201, 2026103201, 2026104201 | The author's office confrontation, held as one medium two-shot across all four segments |

The four-segment scene is what the author calls V9. It is the workflow's main example, so I ran it three times from the
author's own graph with the seeds changed by a fixed offset.

# HouseExpo sample fixtures

40 house-boundary JSON files, verbatim in the upstream schema, sampled from
[TeaganLi/HouseExpo](https://github.com/TeaganLi/HouseExpo) (MIT licensed,
Copyright (c) 2019 Tingguang Li — see upstream `LICENSE`) for use **only**
as a structural stress-test corpus for `zone_geometry.py` (see
`genesis/engine/tests/test_houseexpo_regression.py`).

## Why these files exist here

`genesis/engine`'s own hand-built fixtures (the Unit 12 L-shape, the small
synthetic rectangles in `test_zone_geometry.py`) are useful but few and
hand-picked. HouseExpo's 35,126 real, vectorized floor plans are a free,
much larger and messier source of boundary polygons — including
self-intersecting ones — to check that `diagnose_shape()` and
`analyze_zones()` never raise and always return internally-consistent
output, regardless of how irregular or noisy the input footprint is.

**This is a structural/robustness corpus only.** HouseExpo carries no Vastu
ground truth, no compass/orientation metadata, and its `room_category`
labels (Kitchen, Bedroom, Office, Lobby, ...) are generic room types, not
Vastu zones. Nothing here is used to validate Vastu *correctness* — see
`test_houseexpo_regression.py`'s docstring for exactly what is and is not
asserted.

## Selection method

- 10 files: the upstream repo's own `HouseExpo/map_id_10.txt` "mini" sample
  set (the IDs the upstream project itself uses for quick smoke-testing).
- 30 files: `random.sample(all_35126_ids, 30)` with `random.seed(42)`,
  drawn from the full `HouseExpo/json.tar.gz` archive (fetched directly
  from the upstream repo at analysis time), excluding the 10 mini-set IDs.

Total: 40 files, ~256 KB. JSON re-serialized compactly (no pretty-printing)
to keep the fixture set small; all field values are unchanged from upstream.
3 of the 40 sampled boundaries are self-intersecting per Shapely's
`is_valid` check — kept deliberately, since exercising `zone_geometry`'s
`buffer(0)` repair path on real (not synthetic) invalid polygons is exactly
the kind of case the hand-built fixtures don't cover.

## Schema (verbatim from upstream)

Each file is a single house:

```json
{
  "id": "<32-char hex string>",
  "room_num": <int>,
  "bbox": {"min": [x1, y1], "max": [x2, y2]},
  "verts": [[x, y], ...],
  "room_category": {"<RoomType>": [[minx, miny, maxx, maxy], ...], ...}
}
```

- `verts` is the house's overall boundary polygon, in **meters**, in
  upstream's own local coordinate frame (no relation to true north).
- `room_category` maps a generic room-type label to one or more axis-aligned
  bounding boxes for rooms of that type — not full room polygons, and not
  guaranteed to lie entirely inside `verts` (upstream data has some boxes
  that spill slightly outside the house boundary; this is real noise, kept
  as-is).

## Regenerating or expanding this sample

No script is checked in for this — the selection was a one-off, run
against a local extraction of `HouseExpo/json.tar.gz` fetched from the
upstream repo. To pull a different or larger sample, fetch
`https://raw.githubusercontent.com/TeaganLi/HouseExpo/master/HouseExpo/json.tar.gz`
(~25 MB) and repeat the same `random.seed(42)` sampling shown above, or
change the seed/count for a different draw.

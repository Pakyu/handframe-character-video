# User Reference Effect Analysis

- Reviewed at: 2026-08-11
- Evidence source: user-supplied local reference video
- SHA-256: `FBE0CD8CF289804D5314E7AA6FECD7038B17D61C07605DE115CCA95854D7A743`
- Media: 1276×718, 30 fps, 26.981587 seconds

## Observed mechanism

Representative frames show two spatially aligned versions of the same shot: the original layer and a stylized character layer. The hand-defined region behaves as a moving visibility mask. As the hands expand or reshape the aperture, more or less of the already aligned stylized layer becomes visible. The stylized face and body remain at the same full-frame locations as the original subject.

The reference does not show the entire stylized frame being scaled or perspective-warped into the hand quadrilateral. Therefore the reusable mechanism is:

1. synchronize source and transformed videos by time
2. resize each once to the common output frame
3. create a dynamic polygon mask from the tracked hands
4. reveal the transformed layer inside the mask and retain the source outside

The window preserves the physical opening motion. When both hands are visible but the thumb/index pairs are still closed, the quadrilateral collapses into a thin line. As the fingers separate, the same four tracked points expand continuously. A placeholder polygon is an editing aid only and must never activate the compositing window when the hands are absent.

## Generalization decision

- Classification: core mechanism
- Promoted rule: `fit_mode=clip`, transformed-layer looping disabled, perspective composition rejected
- Rejected interpretation: four-corner perspective mapping of the whole transformed frame into the hand polygon
- Missing evidence: the reference alone does not prove a particular hand-tracking algorithm, edge-feather amount, or behavior under occlusion and motion blur

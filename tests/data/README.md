`face_*.jpg` come from MediaPipe's public `business-person.png` test asset, placed
in a 640x480 frame at webcam scale. The half and closed versions have their
eyelids painted in, which gives the end-to-end test a known number of blinks.

`real_blinks.npz` holds per-frame numbers (time, eye aspect ratio, yaw, pitch) from
two public-domain US government videos of a person speaking to a camera, the
2016-02-06 and 2016-01-16 weekly addresses on Wikimedia Commons. It contains no
images. Each video appears twice: as framed for a webcam, and degraded with blur,
darkness and noise to imitate a cheap camera at night. Blink times were labelled
by inspecting eye crops; `clear` marks an unmistakable lid closure.

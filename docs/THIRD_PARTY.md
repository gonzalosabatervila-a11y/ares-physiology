# Third-party inspiration and attribution

## Pulsr (2026)

- Project: https://github.com/0xCodez/pulsr
- License: MIT
- Copyright (c) 2026 Pulsr contributors

ARES Scientific Atelier uses an original CSS visualization inspired by Pulsr's
recovery orb, with no Metal shader or Swift UI assets copied. The original
Pulsr project is released under the MIT License; its copyright and permission
notice are retained below for attribution.

MIT License

Copyright (c) 2026 Pulsr contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

### Why ARES does not copy Pulsr scores

Pulsr consumes Apple Health's nocturnal HRV SDNN and minute-level heart rate;
WHOOP's API provides nocturnal RMSSD, cycle/workout summaries and sleep records.
SDNN and RMSSD are not interchangeable and minute-by-minute HR samples are not
present in ARES's current data contract.

Therefore ARES displays WHOOP's original recovery score and retains its own
baseline and training models. Pulsr's HRV-weighted Recovery, minute-level TRIMP
Strain, minute-level Stress and model-based Body Age are **not** presented as
ARES measurements without compatible inputs and validation.

Inspiration and provenance are distinct from endorsement: ARES is not
affiliated with Pulsr, Apple or WHOOP.

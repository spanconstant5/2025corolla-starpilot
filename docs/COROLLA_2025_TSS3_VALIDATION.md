# Corolla TSS3 validation gates

This is the evidence gate for the exact 2025 US Corolla Hybrid EPS
`8965F1208000 / 8A3111213000`. The retained 2023 US-built non-hybrid SE
package is useful for E210 geometry and topology comparison, but it is not
authority for the 2025 control messages.

## Current result

| Area | State | Evidence / next gate |
|---|---|---|
| RAM signer install | Proven | Exact F181 and payload SHA; live `0x777` to `0x7A9` probe passed in 9.72 ms. |
| Bench peer health | Inconclusive | Brake `0x102D` fault bits were clear. Corolla returned an 8-byte `0x102F`; Kai's current Camry decoder requires 10 bytes. This is not a confirmed fault and is not a health pass. |
| Signed inactive `0x08A` | Offline/probe proven | Exact 28-byte inactive application and valid trailer are proven. Panda acceptance and sustained publication must be confirmed from an in-car route. |
| Runtime signer preflight | Prewarmed handoff implemented, route validation pending | Clean routes at `23560df817` proved the tuple/retry fixes: 596 accepted `0x777` frames, zero rejections, sequence mismatches, or nonzero longitudinal fields. They also isolated the remaining delay to `card` startup after the installer released Panda. The guided flow now prewarms `card` offroad and keeps it alive through valid on-road Corolla CAN, so its send subscription is already waiting when the cooperative Panda lease ends. |
| Vehicle receive topology | Route-replay proven | The full-rate Corolla stream is on Panda bus 2. CarState and Panda safety consume it there; the incomplete forwarded bus-0 TX-record stream is not used as a receive source. |
| Fingerprint recovery | Three-bus route proven | When FPv1 is ambiguous, recovery requires explicit Corolla identity authority (stored selection or prior exact EPS signer probe), at least 120 DLC-exact Corolla census matches on each mirrored vehicle plane (buses 0 and 2), no conflicting census DLC, and the complete retained CAN-FD ADAS census on bus 1. Topology alone cannot identify the car. |
| Lateral control | Implemented, road validation pending | Angle command uses the signed `0x08A`; 55-degree wheel-angle bound and measured-angle inactive check are enforced. |
| Longitudinal control | Disabled | Interface, controller, and Panda safety all keep both acceleration fields zero. IDs and limits are not yet accepted as Corolla-live evidence. |

## Automatic evidence

Every guided UI run persists its original artifacts below
`/data/tss3-oracle-runs/ui-bringup-*`. StarPilot also writes
`openpilot-bringup-summary.json`, classifying vehicle health as `healthy`,
`fault`, or `inconclusive` without turning an unsupported diagnostic layout
into a fault.

During normal control, the request transport writes compact lifecycle records
to the route log:

- first successful inactive signer preflight, which gates PCM engagement;
- first valid EPS signer response and latency;
- first Panda-accepted host `0x08A` publication;
- request, response, supersede, publication, acceptance, and rejection totals
  when the request plane releases;
- explicit authority failure reason.

This allows a parking-lot test to finish without live SSH. Preserve and upload
the `rlog.zst` afterward; video files are not needed for this analysis.

The October 23 route pair also established that forwarded stock traffic may be
split between bus 0 RX records and `src=0x80` TX receipts. Before the topology
fix this caused `canBusMissing`, `canError`, and `controlsMismatch`, so normal
control never issued a signer request. Replaying the native bus-2 stream after
the fix produces zero invalid Panda RX checks. A final parser invalid state at
the end of one short log was caused only by the recording ending 157 ms after
its last wheel-speed frame.

The October 26 installer archive contains four successful status-zero live
probes, including a 13.43 ms response immediately before the stationary route.
The route then exposed a deterministic runtime-only mismatch: every one of its
71 complete applications used an application sequence one behind its outer
carrier sequence. The aligned transport starts with the exact installer-proven
sequence-1 carrier and remains aligned through carrier wrap.

The next post-install pair at commit
`0e3b5bf1d21d5efe91b8e5379abb48bcbd14abc3` ruled out sequence alignment as the
remaining cause. Across both logs, Panda accepted all 224 aligned `0x777`
frames forming 56 complete applications, with zero rejected publications and
zero nonzero longitudinal fields, but the EPS returned no `0x7A9`. In the log
that directly followed installation, the first runtime request began 10.296 s
after the successful installer probe: about 4.9 s was spent reaching recovered
fingerprint and another 5.4 s waiting for controls initialization. The vehicle
also moved at up to 1.048 m/s and changed gears, so this pair is diagnostic
evidence and not a stationary validation pass.

The next stationary route at clean commit
`4d8c1700bfc0c57861178b143d3823c3d694b3d4` proved that the controls-startup
bridge ran as designed but still started too late. The car remained in Park at
zero speed. Panda accepted all 28 frames forming seven aligned applications,
with zero rejections, zero sequence mismatches, and zero nonzero longitudinal
fields; the EPS returned no `0x7A9`. The first request began 3.466 s after the
successful installer probe. There were no Panda faults, invalid RX checks, TX
blocks, `canError`, `canBusMissing`, or `controlsMismatch` events.

For the next attempt, a persisted Corolla TSS3 selection still bypasses
VIN/firmware queries that have produced no usable identity on this car, while
final identity still requires the complete three-bus live census. The inactive
transport now starts after `card` observes the mirrored 32-byte native `0x08A`
plane on buses 0 and 2, continues through the fingerprint census, and remains
the sole startup sender while the Corolla parsers warm up. On the first valid
CarState, the normal Toyota interface takes over preflight. Every phase uses the
same byte-exact inactive application. None can arm replacement ownership or
publish host `0x08A`, and both longitudinal fields remain zero.

Two later post-install captures at clean commit
`26b862f9976492775e8faaa9b8012caf62262e0d` began 0.620-0.657 s after separate
successful installer probes. Fingerprint recovery repeatedly selected
`TOYOTA_COROLLA_TSS3`, and Panda accepted the delivered aligned `0x777` frames
with zero rejections, sequence mismatches, or nonzero longitudinal fields.
There was still no `0x7A9` or host `0x08A`. Both captures show why: the helper's
sequence-1 publication was generated before the `sendcan` subscriber was ready
and never reached Panda, while the one-second retry delivered sequence 2 only
at 2.169-2.231 s after install. After recovery, `card` then repeatedly crashed
because its parser path supplies raw CAN tuples while the helper expected
attribute-bearing `CanData` values. The startup-only transport now accepts both
forms and retries an unanswered challenge every 100 ms until the first valid
response. It remains inactive, never emits host `0x08A` or an ownership admin
frame, and returns to the one-second cadence once signer liveness is proved.

The October 26 follow-up at clean commit
`23560df8176e251b9009e47a957aa99e58f78d21` proved those tuple and retry fixes
and isolated the remaining miss to process startup. Two installer runs passed
the exact Corolla F181, payload, and live signer probe in 11.10 ms and 9.19 ms.
The corresponding routes recovered `TOYOTA_COROLLA_TSS3`, entered Toyota safety
without a `card` crash, and recorded 596 accepted `0x777` frames with zero
rejections, application/carrier sequence mismatches, or nonzero longitudinal
fields. Neither route received `0x7A9` or published host `0x08A`. In the fully
stationary Park route, the first accepted runtime request still arrived 1.725 s
after the installer completed; in the second route the first generated
application was dropped during subscriber startup and sequence 2 arrived
1.267 s after install. The second vehicle moved at up to 0.419 m/s and is not a
stationary pass.

The guided UI now sets a private, non-logged startup bridge before launching
the installer. Manager uses it to start `card` while the car is still off, so
Python imports and the `sendcan` subscription complete during the installer's
cooperative Panda lease and the operator's OFF-to-READY sequence. A failed
installer clears the bridge immediately. A proven install retains it until
`card` has identified the exact Corolla, observed valid CAN, and seen the
manager's on-road transition. At that point `card` restores
`FirmwareQueryDone` (which manager intentionally clears at the transition),
then releases the bridge; the ordinary `ControlsReady` path remains solely
responsible for selecting Toyota safety. This does not require NRTD, does not
share direct Panda ownership, and does not relax fingerprint, signer, safety,
or longitudinal gates.

Run the offline report with:

```bash
python3 tools/corolla_tss3_route_evidence.py /path/to/rlog.zst \
  --output /tmp/corolla-tss3-evidence.json
```

The report separates native `0x08A`, candidate `0x160`, signer `0x7A9`, host
`sendcan` publications, `0x777` and `0x08A` TX receipts, payload-matched host
acceptance, and the transport lifecycle records. It also reconstructs complete
four-frame Corolla signer applications and independently checks both redundant
longitudinal fields for zero. It also requires each application's six-bit
`REQUEST_SEQUENCE` to equal the low six bits of the outer carrier sequence; the
first runtime preflight therefore reproduces the installer's proven sequence-1
request byte for byte. Forwarded stock `0x08A` also produces TX receipts and is
never counted as host acceptance without a matching `sendcan` frame. The report
also lists which bytes changed in native candidate frames.

## In-car gate order

1. Install the volatile signer from OFF using the guided UI startup catcher.
   Do not move the car until the live signer probe has passed and the vehicle
   has returned to READY without affirmative Brake/EPS fault bits.
2. With the service brake firmly held, select Drive, release the parking brake,
   close all doors, enable cruise main, and engage/disengage once without allowing
   the car to move. Before the engagement edge, require a
   `preflight_signer_live` record from the startup handoff; otherwise PCM engagement remains blocked. Park
   is not an engageable gear and cannot exercise the normal request plane.
   Require a `signer_response_live` record, a `host_08a_active` record, accepted
   `0x777` and `0x08A` publications, zero rejected publications, and zero nonzero
   longitudinal fields in both reconstructed signer applications and host
   publications. Also require zero carrier/application sequence mismatches.
3. With a spotter on private, controlled pavement, validate low-speed lateral
   tracking and driver override. Stop on any cluster fault, screen instability,
   request-plane authority failure, or missing signed-publication cadence.
4. Only after the stationary and low-speed route passes, compare requested
   steering angle, measured angle, Panda acceptance, signer latency, and
   superseded generations over a longer lateral route.

## Longitudinal research gate

Do not enable longitudinal from the 2023 `0x160` path or from the current
Camry-derived `0x08A` envelope by assumption. First collect a stock-ACC rlog on
this exact car that includes transitions through cruise off, armed, active,
acceleration, deceleration, driver gas, driver brake, standstill, and resume.
For native `0x08A` and any live `0x160`, establish:

- producing ECU, destination bus, DLC, cadence, and counter/freshness fields;
- requested-acceleration encoding, scale, sign, inactive value, and redundant
  field relationship;
- request/allocation IDs and all fixed or state-dependent envelope bytes;
- pedal disengagement behavior, standstill/resume behavior, and stock bounds;
- whether changing an application field still yields a valid signer response;
- Panda limits for acceleration, jerk, gas/brake disagreement, request
  redundancy, controls-allowed state, and message timeout.

Until those items are established, `openpilotLongitudinalControl` remains
false, CarController always requests zero acceleration, and Panda independently
rejects a nonzero value in either redundant acceleration field.

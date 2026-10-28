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
| Runtime signer preflight | Lightweight socket handoff implemented, button validation pending | Clean routes at `23560df817` proved the tuple/retry fixes: accepted `0x777` frames had zero rejections, sequence mismatches, or nonzero longitudinal fields. They also isolated the remaining delay to the `sendcan` subscriber connection after the installer released Panda. The guided flow now binds only card's messaging sockets offroad, waits for an explicit readiness acknowledgement, and defers the full controls stack until on-road. |
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

The guided UI creates a private, tokenized `/tmp` startup lease before launching
the installer. Manager starts a lightweight card launcher while the car is still
off. It binds the normal `can` and `sendcan` messaging sockets, then explicitly
acknowledges readiness to the UI. The external installer is not launched unless
that exact per-run acknowledgement arrives. Full `card` imports, realtime setup,
fingerprinting, and safety initialization remain strictly on-road. This gives
native pandad's restarted `sendcan` subscriber time to connect to the already
bound publisher without running the controls stack offroad. A failed installer
clears the lease immediately. A proven install retains it until `card` has
identified the exact Corolla, observed valid CAN, and seen the manager's on-road
transition. The ordinary `ControlsReady` path remains solely responsible for
selecting Toyota safety. This does not require NRTD, does not share direct Panda
ownership, and does not relax fingerprint, signer, safety, or longitudinal
gates.

The October 27 installer again passed the exact live signer probe on its first
attempt in 10.31 ms, with four accepted frames and zero rejects. Its following
61.692-second route was stationary in Park and recovered
`TOYOTA_COROLLA_TSS3`; Panda transitioned from ELM327 to Toyota safety param
53321 with no faults. It accepted 312 `0x777` fragments with zero rejects, and
all 75 complete logged applications had aligned carrier/application sequences
and zero in both longitudinal fields. There was no `0x7A9` response or host
`0x08A`. The first accepted runtime fragment arrived 1.115 s after the installer
completed, and the route recorded three startup `controlsMismatch` samples.
Most importantly, `initData` proves this run was still clean commit
`23560df8176e251b9009e47a957aa99e58f78d21`, so it did not exercise the
prewarmed-card change at `e08f46fe6a89f016054011a5dbcd85a4413a55fb`.

Starting with `tss3-openpilot-bringup-summary-v2`, every guided UI archive
records the active openpilot version, commit, branch, remote, dirty state, and
whether this build requested and received acknowledgement from the startup
bridge. This makes deployment provenance available in the small installer
archive instead of requiring a later qlog/rlog to discover that the wrong tree
was installed.

The first button attempt intended to validate
`94f33572becdd635827f4a68ab920ad078c4fb5e` caused the comma device to reboot
before it could write a route. The only new button-time action was starting the
entire heavy `card` process offroad. That design has been removed. The
replacement launcher performs only messaging-socket and token-file
coordination offroad, reports an exact readiness token, and fails closed without
starting the external tool if it is not ready within four seconds. The full
card process cannot start until `IsOnroad` is true. The token file is the single
source of truth because deployed builds use a tracked prebuilt ARM Params module;
adding a source-only Params key otherwise produces `UnknownKeyName` on-device.

The first button attempt on `e92c5cb6cc2142f91235d121307f70a89caf8f50`
confirmed that exact mismatch: the UI contained the failure and displayed
`Could not prepare Corolla signer handoff — UnknownKeyName` before launching the
installer. No vehicle route was expected from that rejected attempt. The next
build removes the bridge key from Params completely; the same per-run token now
drives manager prewarm, launcher acknowledgement, cancellation cleanup, and the
final valid-CAN handoff.

Two guided runs on `1f5c255447ecffaf3c1d412fd3756920a2f8a82c` proved that
token-file handoff: both archives record the exact commit and an acknowledged
startup bridge. Both boot-catch installs matched the Corolla F181 and payload,
used the expected `DEV-9250dab8-DEBUG` signed Panda firmware, and returned a
successful first-attempt `0x777` to `0x7A9` probe in 10.26 ms and 12.37 ms, with
four accepted and zero rejected frames each. The associated 5.439-second and
50.944-second routes stayed in Park at exactly 0 m/s, recovered the exact
non-fuzzy Corolla fingerprint, kept openpilot longitudinal disabled, and had no
Panda faults, invalid RX checks, heartbeat loss, rejected TX, `canError`,
`canBusMissing`, or `controlsMismatch`. The longer route reached Toyota safety
param 53321.

The remaining failure is after the initial live probe. Across both routes, all
356 runtime `0x777` fragments were accepted and formed 89 aligned applications,
with zero rejected publications, sequence mismatches, or nonzero longitudinal
fields. None received runtime `0x7A9`, so no host `0x08A` could be published.
The first accepted runtime requests were only 0.730 s and 0.883 s after the
successful installer probes. This rules out publisher startup and shows that the
remainder of the vehicle boot transition invalidates the early boot-catch RAM
resident before normal card operation.

The guided flow now has a guarded second phase. After the boot-catch establishes
the target and startup completes, it waits for fresh live state proving the exact
Corolla, Park, 0 m/s, cruise and controls inactive, longitudinal disabled, valid
CAN, and fault-free Toyota safety param 53321. Only then does it use the kit's
reviewed application-programming entry to reinstall the same volatile payload.
It requests the ordinary onroad process cycle afterward and requires fresh proof
that the same stationary and Toyota-safety gates returned before reporting the
result. Failure of any gate prevents the second install or fails closed with a
do-not-drive result.

The installer summaries marked these runs dirty because the persisted `GitDiff`
included runtime-selected theme symlinks. Both route `initData` records are
authoritative and report `dirty=false` at the exact commit. Future summaries use
the same build metadata as `initData`, so runtime theme selection no longer
mislabels an exact deployment as an uncommitted tree.

The October 27 follow-up at clean commit
`4967ab4f9586b54dd741428e74f04fa7cd605077` exercised that guarded second phase.
Both routes recovered the exact non-fuzzy Corolla fingerprint with longitudinal
disabled. The stationary route stayed in Park at 0 m/s, reached Toyota safety
param 53321 without Panda faults, heartbeat loss, invalid RX checks,
`canBusMissing`, `canError`, or `controlsMismatch`, and delivered 104 accepted
runtime `0x777` fragments with zero rejects, sequence mismatches, or nonzero
longitudinal fields. The signer still returned no runtime `0x7A9`, and no host
`0x08A` was published. The post-start installer reached the application and then
received NRC `0x22` (conditions not correct) for PROGRAMMING. Every CarState
sample in the stationary route had `brakePressed=false`; the parking brake, Park,
standstill, and other software gates were present. The next build therefore adds
the missing programming interlocks: it proves the parking brake and service brake
for the stable interval before installation, tells the operator to hold both
through the handoff, and proves them again after controls return. It does not retry
a rejected handoff or relax any fingerprint, safety, or longitudinal gate. The
second route changed gears and reached 0.280 m/s, so it is diagnostic evidence and
not a stationary validation pass.

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

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

Run the offline report with:

```bash
python3 tools/corolla_tss3_route_evidence.py /path/to/rlog.zst \
  --output /tmp/corolla-tss3-evidence.json
```

The report separates native `0x08A`, candidate `0x160`, signer `0x7A9`, host
`sendcan` publications, `0x777` and `0x08A` TX receipts, payload-matched host
acceptance, and the transport lifecycle records. It also reconstructs complete
four-frame Corolla signer applications and independently checks both redundant
longitudinal fields for zero. Forwarded stock `0x08A` also produces TX receipts
and is never counted as host acceptance without a matching `sendcan` frame. The
report also lists which bytes changed in native candidate frames.

## In-car gate order

1. Install the volatile signer from OFF using the guided UI startup catcher.
   Do not move the car until the live signer probe has passed and the vehicle
   has returned to READY without affirmative Brake/EPS fault bits.
2. With the service brake firmly held, select Drive, release the parking brake,
   close all doors, enable cruise main, and engage/disengage once without allowing
   the car to move. Before the engagement edge, require a
   `preflight_signer_live` record; otherwise PCM engagement remains blocked. Park
   is not an engageable gear and cannot exercise the normal request plane.
   Require a `signer_response_live` record, a `host_08a_active` record, accepted
   `0x777` and `0x08A` publications, zero rejected publications, and zero nonzero
   longitudinal fields in both reconstructed signer applications and host
   publications.
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

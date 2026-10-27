# Agensi Marketplace Release

This directory turns the public skills into reviewable marketplace packages. It
does not change the repository licence: the source remains available under
[MIT](../LICENSE). A marketplace listing is a tested distribution of that work,
not a claim of exclusivity.

See [Release status](RELEASE_STATUS.md) for current validation evidence and
submission gates.

## Release model

The two skills are independent products:

| Package | Product focus | Runtime boundary |
| --- | --- | --- |
| `hull-lines-dxf` | Deterministic offsets-to-DXF workflow with bilingual drawings and audit reports | Python 3.10+; no network after dependencies are installed |
| `rhino-basic-hull` | Stage-controlled Rhino hull construction and source/geometry review | A Rhino version with RhinoCommon and its Python runtime |

Keep them as separate listings first. A bundle can be created after both are
live and have real usage evidence.

## Release commands

Check metadata and package limits without writing a ZIP:

```bash
python scripts/build_agensi_release.py --check
```

Build deterministic release ZIPs and hashes:

```bash
python scripts/build_agensi_release.py --out dist/agensi
```

The build excludes tests, caches and development-only files. It keeps text,
code, templates and reference data, includes the root MIT licence, and rejects
unsafe file types, oversized production scripts or incomplete listing fields.

## Submission sequence

1. Run the environment check for `hull-lines-dxf` and the complete test suite.
2. Confirm the seller is at least 18 and has legal authority to publish all
   bundled examples.
3. Choose the final price and payout method in Agensi Creator Studio. Paid
   listings require Stripe Connect where supported, otherwise Zoneless KYC and
   a Solana USDC wallet.
4. Upload the generated ZIP, the 512 x 512 logo, the listing description and
   the full example session.
5. Review the detected permissions and add every missing runtime requirement
   or limitation.
6. Keep the listing inside Agensi. Do not add outside checkout or paid-upgrade
   links.
7. Record review, approval, price, payout and update dates in the release log.

`rhino-basic-hull` must remain staged until an actual Rhino runtime session has
loaded the purchased package, executed the read-only audit path and returned a
native report. File review and mathematical checks alone are `NOT_CHECKED` for
native Rhino behaviour.

## Pricing decision

Agensi requires the seller to choose the price. For an initial release, a paid
listing is reasonable only if buyers receive clear packaging and maintenance
value over the public MIT repository. The platform's own guidance places
multi-file skills with scripts and references around USD 12-25; that is a
comparison point, not a requirement. Avoid subscriptions until there is a
defined update and support cadence because annual plans must remain available
for twelve months.

## Legal and evidence boundaries

- The skill source is MIT licensed. Agensi delivery restrictions do not remove
  rights already granted by that licence.
- Do not include client hulls, proprietary lines plans or measured vessel data
  in the package.
- Generated geometry is decision support and source traceability, not a
  classification, stability, structural, hydrodynamic or regulatory approval.
- A file audit is not a native AutoCAD or Rhino visual check.
- Refunds within Agensi's 30-day guarantee, chargebacks and fraud reversals
  reverse the creator's share.


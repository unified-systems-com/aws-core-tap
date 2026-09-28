# Changelog

## [0.6.0](https://github.com/unified-systems-com/aws-core-tap/compare/v0.5.0...v0.6.0) (2026-09-28)


### ⚠ BREAKING CHANGES

* **collector:** per-entry persist_configuration flag replaces the global switch

### Features

* AWS Organizations, Identity Center and Transit Gateway design vocabulary ([7bf4b9e](https://github.com/unified-systems-com/aws-core-tap/commit/7bf4b9e324b0deb1591930f6eb41dce9c2f82fbd))
* AWS Organizations, Identity Center and Transit Gateway design vocabulary [via highbar] ([2cc17ac](https://github.com/unified-systems-com/aws-core-tap/commit/2cc17ac37950ff4d9c9f7497f0d272687b640b37))
* **aws_account, aws_vpc, aws_subnet:** designed resources may omit their AWS ids [via highbar] ([c62f68d](https://github.com/unified-systems-com/aws-core-tap/commit/c62f68d35b3a576f7513966e03e7154d498d2448))
* **aws_account:** a designed account may exist before AWS mints its id ([ccfae1c](https://github.com/unified-systems-com/aws-core-tap/commit/ccfae1c16dfae5f44ec4d9f8ec891ffa5c3b6916))
* aws_core vocabulary part 2 — placement edges, Direct Connect, PrivateLink, DNS Firewall, Private CA [via highbar] ([1067b95](https://github.com/unified-systems-com/aws-core-tap/commit/1067b95e472ad67456d9d23357ef66573edffa6b))
* **aws_vpc, aws_subnet:** designed networks may omit their AWS ids ([0d21433](https://github.com/unified-systems-com/aws-core-tap/commit/0d21433218aac42341b63ddd018296e33dfb1c91))
* **collector:** an unreviewed manifest entry is never persisted ([c7ebf24](https://github.com/unified-systems-com/aws-core-tap/commit/c7ebf2455d5dfc2a939d32ca6c9f46ac2709053b))
* **collector:** an unreviewed manifest entry is never persisted; add-aws-type asks the requester [via highbar] ([1327a80](https://github.com/unified-systems-com/aws-core-tap/commit/1327a806700d75c0e624f6411a98e599bad60a45))
* **collector:** per-entry persist_configuration flag (off for credential-bearing types) + response sensitivity in the manifest [via highbar] ([4348819](https://github.com/unified-systems-com/aws-core-tap/commit/4348819adae4f0882c7d499fe8f215efc4f3bd50))
* **collector:** per-entry persist_configuration flag replaces the global switch ([02a099f](https://github.com/unified-systems-com/aws-core-tap/commit/02a099fe22bf6269b4cff806fc9c3feaec33877a))
* **collector:** stop persisting raw AWS responses; declare response sensitivity per manifest entry ([2807d2e](https://github.com/unified-systems-com/aws-core-tap/commit/2807d2ebbae65fdc986aedac6a860be36860914c))
* design-phase gaps found by the Teleport and GitLab corpora ([828f838](https://github.com/unified-systems-com/aws-core-tap/commit/828f838f0623bc9957820724ee485f7e7b499ba2))
* design-phase gaps from the Teleport + GitLab corpora [via highbar] ([10b0eb7](https://github.com/unified-systems-com/aws-core-tap/commit/10b0eb7a072798314c2519ac80a1985d60dd3965))
* **edges:** RESIDES_IN_AZ — a subnet's availability zone ([3ea1fc5](https://github.com/unified-systems-com/aws-core-tap/commit/3ea1fc58cd388e5efb5feb2bfa7f96baf57f64ee))
* **edges:** RESIDES_IN_AZ places a subnet in its availability zone ([6f52e84](https://github.com/unified-systems-com/aws-core-tap/commit/6f52e84561b2b4de9c0ec08b0a189aad3409e97d))
* **layout-hints:** siblings in a row sharing layout:column stack in one column ([7936a71](https://github.com/unified-systems-com/aws-core-tap/commit/7936a71079271b366f6540678f155bed0874252d))
* **models:** keep the security facts the off types lost as typed fields ([a8884e6](https://github.com/unified-systems-com/aws-core-tap/commit/a8884e654727cfbe84d19729de6e50a5e1983f9a))
* **models:** keep the security facts the storage-off types lost as typed fields (Q44a) [via highbar] ([c5cc873](https://github.com/unified-systems-com/aws-core-tap/commit/c5cc87369384e2a3113e1b5061ad3dd3d514e22f))
* **models:** record CloudFront origin custom-header presence, never the value [via highbar] ([18d6e37](https://github.com/unified-systems-com/aws-core-tap/commit/18d6e372e9474dc95dd708440a57d2e8dacec030))
* **models:** record whether each CloudFront origin has custom headers, never the value ([572221a](https://github.com/unified-systems-com/aws-core-tap/commit/572221a56ed7f99c081002d0237dde0f41e3a682))
* network-plane vocabulary (placement, Direct Connect, PrivateLink, DNS Firewall, Private CA) ([ead8144](https://github.com/unified-systems-com/aws-core-tap/commit/ead8144e6edf6783be6aab797200a2b5c0ad6c70))
* **pages:** /aws dashboard, organization and network pages, and the aws-counts panel ([085a9f6](https://github.com/unified-systems-com/aws-core-tap/commit/085a9f6c4096f8544a7c6dd76275226fb6facfd4))
* **pages:** /aws dashboard, organization and network pages, and the aws-counts panel [via highbar] ([f27107c](https://github.com/unified-systems-com/aws-core-tap/commit/f27107c69e8acf7fd706bad1651eb6e3319b620a))
* **pages:** /aws/network nests each VPC around its subnets, by zone ([d30fcaf](https://github.com/unified-systems-com/aws-core-tap/commit/d30fcaf0e0ee7cda219bd37abe30a7c14e765a38))
* **pages:** /aws/organization draws the OU tree only, placed by layout tags ([6c93fb4](https://github.com/unified-systems-com/aws-core-tap/commit/6c93fb468f448f0745c139e9118666b8240601f2))
* **pages:** organization graph draws the OU tree only, placed by layout tags ([2d97d3e](https://github.com/unified-systems-com/aws-core-tap/commit/2d97d3ee3eebc896ea4a3663800c1693abf7ee52))
* **pages:** rows and stacks from layout tags on the organization graph ([a5ed482](https://github.com/unified-systems-com/aws-core-tap/commit/a5ed4820ca9d161d96a054e4ae1ac6e0501aa8c9))
* **pages:** the network graph nests each VPC around its subnets, by zone ([78d4236](https://github.com/unified-systems-com/aws-core-tap/commit/78d4236ee24fd81c721a9ce33b19d39d58f77439))
* **regions:** add AWS GovCloud (US) regions + AZs [via highbar] ([4e62476](https://github.com/unified-systems-com/aws-core-tap/commit/4e624769263f4e64bcce2c98643dc5d041639619))
* **regions:** add the AWS GovCloud (US) regions and their AZs ([e7192fb](https://github.com/unified-systems-com/aws-core-tap/commit/e7192fba66ac8498c0b09af6599e2dd35bc67a48))


### Bug Fixes

* AWS-only ASN ranges, unobserved SCP provenance, Sonar migration exclusion ([f1d84c2](https://github.com/unified-systems-com/aws-core-tap/commit/f1d84c28b84cdf4c70d448838dd38c50cc332e54))
* **boot:** pin the commit beside every git source's rev in the CI record ([51725ac](https://github.com/unified-systems-com/aws-core-tap/commit/51725ac0f145f5f3bbcad5eff734ce3b48733ec6))
* **boot:** pin the commit beside every git source's rev in the CI record [via bom-bom] ([e64efa1](https://github.com/unified-systems-com/aws-core-tap/commit/e64efa1fcaecaa6d3a0c94e1fc43157883598891))
* **counts:** every compliance boundary gets a tile, so an unscoped one shows 0 ([5d4eb53](https://github.com/unified-systems-com/aws-core-tap/commit/5d4eb53759dbb50b19c37f536ce79df5ea7d0f12))
* **identity:** every aws_core type declares its natural key; unobserved security facts default to null ([0770ce3](https://github.com/unified-systems-com/aws-core-tap/commit/0770ce3fab582a31f11eb73976aa206c784a544e))
* **identity:** every aws_core type declares its natural key; unobserved security facts default to null [via highbar] ([e0b65c4](https://github.com/unified-systems-com/aws-core-tap/commit/e0b65c47b2b858a6d26027ab862ba34d1d153a91))
* **identity:** the ELB key comment covers all three load balancer types ([ecb6f74](https://github.com/unified-systems-com/aws-core-tap/commit/ecb6f743f1411132d93bd4510a1d556b96a28bcf))
* key service control policies on their ARN ([1a05bd5](https://github.com/unified-systems-com/aws-core-tap/commit/1a05bd506332cca3f8feb86cc1c7e31581bd829f))
* **layout-hints:** ordered siblings always precede unordered ones; no keyed reads ([de65254](https://github.com/unified-systems-com/aws-core-tap/commit/de65254cc6de9a224e0917eb42f83e3258415b07))
* **manifest:** declare tag values carried in the raw envelope; enforce it per tag lane ([442ebbf](https://github.com/unified-systems-com/aws-core-tap/commit/442ebbf4e238a8aa45a78114307c8a776ca0af1e))
* **models:** origin_access "none" means no OAC or OAI, not public; prove a denied GetRoutes stores NULL ([661bfb3](https://github.com/unified-systems-com/aws-core-tap/commit/661bfb3de58cd5d4016f55fcc85bbca5122832a6))
* organization partition accepts aws-cn ([72268f1](https://github.com/unified-systems-com/aws-core-tap/commit/72268f180ecd3159dfd9ba9cd1bc0899fae670ad))
* **pages:** build baseSizes without a keyed write (Codacy object-injection sink) ([a7430cc](https://github.com/unified-systems-com/aws-core-tap/commit/a7430cc047c801516235a146d475d83452329b0d))
* **pages:** bundle v0.3.1 so an existing grid re-imports the corrected Subnets search ([17d7e27](https://github.com/unified-systems-com/aws-core-tap/commit/17d7e279306bf4f6370ff02d870ff928d023fe4a))
* **pages:** Maps instead of keyed object writes in the network nesting (Codacy object-injection sink) ([990e3fb](https://github.com/unified-systems-com/aws-core-tap/commit/990e3fb3ea2f3dea63f5cfc2ec414c572d9a2efe))
* **pages:** sort availability zones with an explicit compare (Sonar S2871) ([5b86632](https://github.com/unified-systems-com/aws-core-tap/commit/5b866322cb1c0330bdd643c7e57b9516239378df))
* **pages:** Subnets search without ORDER BY; zone-less subnets as a compact block ([1bafbb7](https://github.com/unified-systems-com/aws-core-tap/commit/1bafbb749f03a7aa6fd8198e4746263cbc1492e1))


### Documentation

* **collector:** correct text the per-entry flag made false ([6d2e970](https://github.com/unified-systems-com/aws-core-tap/commit/6d2e970d2980bea014429cabcb6bea1d48d18e52))
* **identity:** say only what AWS documents about resource-ID uniqueness ([e28c41e](https://github.com/unified-systems-com/aws-core-tap/commit/e28c41edb4f236351123129b0648aaa7006854d2))
* **layout-hints:** state fill's lone-column case as the code does it ([80d4c84](https://github.com/unified-systems-com/aws-core-tap/commit/80d4c8439f3f28fe411119ab6d6205761000763f))
* **skill:** a requester can keep an entry off, but storing a credential location stays the owner's ruling ([c5cd2c5](https://github.com/unified-systems-com/aws-core-tap/commit/c5cd2c527f750fa0f9320349c5c59f0ded6e1e14))
* **spec:** page-network-3/-4 cite only what was checked; the layout is not yet observed ([b8f3f10](https://github.com/unified-systems-com/aws-core-tap/commit/b8f3f1011f2999cf8854d9180ba150658e1000d4))

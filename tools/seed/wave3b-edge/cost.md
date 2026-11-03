# Wave 3b edge cost estimate

Region `us-gov-west-1`, partition `aws-us-gov`. Source key: **E** = estimate or recollection, no price file read for it.

Time box 1 hour (every resource is created in under two minutes; E)

| Resource | Quantity | Rate | Per hour | 1 hour | Source |
| --- | ---: | --- | ---: | ---: | :---: |
| WAF Classic rule and rate-based rule | 2 | $1.00 per rule per month, prorated hourly | $0.00274 | $0.00274 | E |
| WAF Classic match sets (IP, byte, geo, regex, size, SQL injection, XSS) | 7 | no charge | $0 | $0 | E |
| Route 53 private hosted zone | 1 | $0.50 per month; not charged if deleted within 12 hours | $0 | $0 | E |
| Route 53 health check, disabled | 1 | $0.50 per month, prorated | $0.00068 | $0.00068 | E |
| Route 53 CIDR collection and traffic policy (no policy instance) | 1 each | no charge; an instance is billed per policy record | $0 | $0 | E |
| API Gateway REST API, stage, key, usage plan, client certificate, HTTP API | 1 each | per request; none is made | $0 | $0 | E |
| Cognito user pool, client, domain, group, resource server, identity pool | 1 each | per monthly active user; none | $0 | $0 | E |
| VPC | 1 | no charge | $0 | $0 | E |

**Total for one hour: about $0.004.** Standing cost left running by mistake: about $0.004 per hour, $0.10 per day. If the
prorating assumptions were wrong and every monthly charge were billed whole: $2.00 + $0.50 = $2.50 once.

Not seeded, and why: `WAFRegional::WebACL` (CreateWebACL: "the creation of new WebACL v1 is no longer permitted"), `ApiGateway::DomainName`, `DomainNameV2`, `DomainNameAccessAssociation` and `ApiGatewayV2::DomainName`
(need an ACM certificate for a domain the account controls), `ApiGateway::VpcLink` and `ApiGatewayV2::VpcLink` (a
Network Load Balancer, billed by the hour), `ApiGatewayV2::Authorizer`, `Stage`, `PortalProduct`, `RoutingRule` (the catalog
allows one CloudFormation type per entity type, and the REST types hold the shared entities; the portal types are not
asked for), `Cognito::UserPoolIdentityProvider` (needs a reachable identity provider), `Route53::DelegationSet`,
`QueryLoggingConfig` and `TrafficPolicyInstance` (public zones only, or billed per policy record), the three `CertificateManager`
ACME types and `CertificateManager::Certificate` (an imported certificate needs a private key in the state).

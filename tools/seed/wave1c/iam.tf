# A SAML provider for an identity provider that does not exist: the certificate in the metadata is public, its private
# key was never written to disk (it was sent to /dev/null), and no role trusts this provider. Nothing private is in the module or the state.
resource "aws_iam_saml_provider" "seed" {
  name                   = "${local.prefix}-saml"
  saml_metadata_document = file("${path.module}/saml-metadata.xml")

  depends_on = [terraform_data.guard]
}

#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$labRel = "terraform/kafka-plugin-lab"
$envFile = Join-Path $env:TEMP "mvr-kafka-plugin-lab.env"
aws configure export-credentials --profile mvr --format env |
  ForEach-Object { $_ -replace '^export ', '' } |
  Set-Content -Encoding ascii $envFile
$wslEnv = "/mnt/c/Users/mesve/AppData/Local/Temp/mvr-kafka-plugin-lab.env"
$wslRepo = "/mnt/c/Users/mesve/projects/network-o11y-demo"
try {
  wsl -e bash -lc "sed -i 's/\r$//' '$wslEnv'; docker run --rm --env-file '$wslEnv' -e AWS_REGION=us-east-1 -e AWS_DEFAULT_REGION=us-east-1 -e AWS_PROFILE= -e AWS_SDK_LOAD_CONFIG=0 -v '${wslRepo}:/repo' -w /repo/${labRel} hashicorp/terraform:1.9 init -input=false"
  if ($LASTEXITCODE -ne 0) { throw "terraform init failed" }
  wsl -e bash -lc "docker run --rm --env-file '$wslEnv' -e AWS_REGION=us-east-1 -e AWS_DEFAULT_REGION=us-east-1 -e AWS_PROFILE= -e AWS_SDK_LOAD_CONFIG=0 -v '${wslRepo}:/repo' -w /repo/${labRel} hashicorp/terraform:1.9 apply -auto-approve -input=false -var=aws_profile= -var=lab_enabled=true"
  if ($LASTEXITCODE -ne 0) { throw "terraform apply failed" }
} finally {
  Remove-Item -Force $envFile -ErrorAction SilentlyContinue
}

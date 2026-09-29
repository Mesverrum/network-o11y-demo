package rule

import (
	"net"
	"os"
	"path/filepath"
	"testing"

	"github.com/kentik/ktranslate/pkg/eggs/logger"
	lt "github.com/kentik/ktranslate/pkg/eggs/logger/testing"
	"github.com/kentik/ktranslate/pkg/kt"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func resetDeviceRules() {
	deviceNameUserTags = nil
	deviceIpUserTags = nil
	deviceCidrUserTags = nil
	deviceRules = nil
}

func loadRules(t *testing.T, yamlBody string) error {
	t.Helper()
	resetDeviceRules()
	l := lt.NewTestContextL(logger.NilContext, t)
	dir := t.TempDir()
	path := filepath.Join(dir, "device-lookup.yaml")
	require.NoError(t, os.WriteFile(path, []byte(yamlBody), 0o644))
	return InitUserDeviceRuleSet(path, l)
}

func TestInitUserDeviceRuleSetEmptyPath(t *testing.T) {
	resetDeviceRules()
	l := lt.NewTestContextL(logger.NilContext, t)
	err := InitUserDeviceRuleSet("", l)
	assert.NoError(t, err)
	assert.Nil(t, GetUserDeviceRuleSet("leaf-br1", "192.168.21.2"))
}

func TestInitUserDeviceRuleSetEmptyFile(t *testing.T) {
	err := loadRules(t, "")
	assert.NoError(t, err)
	assert.Nil(t, GetUserDeviceRuleSet("x", "1.2.3.4"))
}

func TestInitUserDeviceRuleSetEmptyMap(t *testing.T) {
	err := loadRules(t, "{}\n")
	assert.NoError(t, err)
	assert.Nil(t, GetUserDeviceRuleSet("x", "1.2.3.4"))
}

func TestInitUserDeviceRuleSetInvalidYAML(t *testing.T) {
	err := loadRules(t, "::: not yaml\n")
	assert.Error(t, err)
}

func TestLookupNameWinsOverIP(t *testing.T) {
	err := loadRules(t, `
leaf-br1:
  site: from-name
  circuit_id: WAN-HQ-BR1
192.168.21.2:
  site: from-ip
  circuit_id: WAN-HQ-BR1
`)
	require.NoError(t, err)
	got := GetUserDeviceRuleSet("leaf-br1", "192.168.21.2")
	require.NotNil(t, got)
	assert.Equal(t, "from-name", got["site"])
}

func TestLookupIPWhenNameMisses(t *testing.T) {
	err := loadRules(t, `
192.168.21.2:
  site: branch1
`)
	require.NoError(t, err)
	got := GetUserDeviceRuleSet("stranger", "192.168.21.2")
	require.NotNil(t, got)
	assert.Equal(t, "branch1", got["site"])
}

func TestLookupMiss(t *testing.T) {
	err := loadRules(t, `
spine1:
  site: hq
`)
	require.NoError(t, err)
	assert.Nil(t, GetUserDeviceRuleSet("leaf-br1", "10.0.0.1"))
	assert.Nil(t, GetUserDeviceRuleSet("", ""))
}

func TestEmptyAndNullTagValues(t *testing.T) {
	err := loadRules(t, `
leaf-br1:
  site: branch1
  circuit_id: ""
  role:
  edge_id: " "
`)
	require.NoError(t, err)
	got := GetUserDeviceRuleSet("leaf-br1", "")
	require.NotNil(t, got)
	assert.Equal(t, "branch1", got["site"])
	// Document current decode: empty string stays; YAML null becomes "".
	assert.Contains(t, got, "circuit_id")
	assert.Equal(t, "", got["circuit_id"])
	assert.Contains(t, got, "role")
	assert.Equal(t, "", got["role"])
}

func TestBlankYAMLKeySkipped(t *testing.T) {
	err := loadRules(t, `
"":
  site: nope
leaf-br1:
  site: branch1
`)
	require.NoError(t, err)
	assert.Nil(t, GetUserDeviceRuleSet("", "1.2.3.4"))
	got := GetUserDeviceRuleSet("leaf-br1", "")
	require.NotNil(t, got)
	assert.Equal(t, "branch1", got["site"])
}

func TestCIDRMatchesContainedIP(t *testing.T) {
	err := loadRules(t, `
192.168.21.0/24:
  site: branch1
`)
	require.NoError(t, err)
	got := GetUserDeviceRuleSet("unknown", "192.168.21.16")
	require.NotNil(t, got)
	assert.Equal(t, "branch1", got["site"])
	assert.Nil(t, GetUserDeviceRuleSet("192.168.21.0/24", ""))
	assert.Nil(t, GetUserDeviceRuleSet("unknown", "10.0.0.1"))
}

func TestCIDRLongestPrefixWins(t *testing.T) {
	err := loadRules(t, `
192.168.0.0/16:
  site: wide
10.0.0.0/8:
  site: other
192.168.21.0/24:
  site: branch1
`)
	require.NoError(t, err)
	got := GetUserDeviceRuleSet("unknown", "192.168.21.16")
	require.NotNil(t, got)
	assert.Equal(t, "branch1", got["site"], "overlapping CIDRs should use longest prefix, not map iteration order")
}

func TestIPv6ExactMatch(t *testing.T) {
	err := loadRules(t, `
2001:db8::1:
  site: lab6
`)
	require.NoError(t, err)
	got := GetUserDeviceRuleSet("n6", "2001:db8::1")
	require.NotNil(t, got)
	assert.Equal(t, "lab6", got["site"])
	expanded := GetUserDeviceRuleSet("n6", "2001:0db8:0000:0000:0000:0000:0000:0001")
	require.NotNil(t, expanded)
	assert.Equal(t, "lab6", expanded["site"])
}

func TestNumericAndBoolTagsCoerceToString(t *testing.T) {
	err := loadRules(t, `
leaf-br1:
  vlan: 100
  core: true
`)
	require.NoError(t, err)
	got := GetUserDeviceRuleSet("leaf-br1", "")
	require.NotNil(t, got)
	assert.Equal(t, "100", got["vlan"])
	assert.Equal(t, "true", got["core"])
}

func TestNestedTagBagFailsUnmarshal(t *testing.T) {
	err := loadRules(t, `
leaf-br1:
  site:
    name: branch1
`)
	assert.Error(t, err)
}

func TestSnmpInitUserTagsNilMapWithDefaults(t *testing.T) {
	err := loadRules(t, `
leaf-br1:
  site: branch1
`)
	require.NoError(t, err)
	d := &kt.SnmpDeviceConfig{
		DeviceName: "leaf-br1",
		DeviceIP:   "192.168.21.2",
		UserTags:   nil,
	}
	assert.NotPanics(t, func() {
		d.InitUserTags("ktranslate", GetUserDeviceRuleSet(d.DeviceName, d.DeviceIP))
	})
	out := map[string]string{}
	d.SetUserTags(out)
	assert.Equal(t, "branch1", out["tags.site"])
}

func TestWhitespaceAroundKeys(t *testing.T) {
	err := loadRules(t, `
"  leaf-br1  ":
  site: branch1
`)
	require.NoError(t, err)
	got := GetUserDeviceRuleSet("leaf-br1", "")
	require.NotNil(t, got)
	assert.Equal(t, "branch1", got["site"])
}

func TestSnmpInitUserTagsDoesNotOverrideExisting(t *testing.T) {
	err := loadRules(t, `
leaf-br1:
  site: from-file
  role: child
`)
	require.NoError(t, err)
	d := &kt.SnmpDeviceConfig{
		DeviceName: "leaf-br1",
		DeviceIP:   "192.168.21.2",
		UserTags: map[string]string{
			"site": "from-device",
		},
	}
	d.InitUserTags("ktranslate-snmp", GetUserDeviceRuleSet(d.DeviceName, d.DeviceIP))
	out := map[string]string{}
	d.SetUserTags(out)
	assert.Equal(t, "from-device", out["tags.site"])
	assert.Equal(t, "child", out["tags.role"])
}

func TestDeviceInitUserTagsNilMaps(t *testing.T) {
	d := &kt.Device{Name: "missing"}
	assert.NotPanics(t, func() {
		d.InitUserTags("ktranslate-flow", nil, nil)
	})
	out := map[string]string{}
	d.SetUserTags(out)
	assert.Equal(t, "ktranslate-flow", out["tags.container_service"])
}

func TestGetUserDeviceRuleSetBeforeInit(t *testing.T) {
	resetDeviceRules()
	assert.NotPanics(t, func() {
		assert.Nil(t, GetUserDeviceRuleSet("x", "1.2.3.4"))
	})
}

func TestParseIPClassification(t *testing.T) {
	assert.NotNil(t, net.ParseIP("192.168.21.2"))
	assert.Nil(t, net.ParseIP("192.168.21.0/24"))
	_, _, err := net.ParseCIDR("192.168.21.0/24")
	assert.NoError(t, err)
}

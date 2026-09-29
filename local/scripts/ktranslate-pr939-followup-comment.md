Nice — patricia `FindDeepestTag` was the right call. I pulled `c588b1d` and re-ran locally.

### Confirmed
- Empty path in `InitUserDeviceRuleSet` is a no-op.
- Keys are trimmed; blank YAML keys skipped; IPv6 exact keys normalized (`2001:db8::1` matches `2001:0db8::0001`).
- Overlapping CIDRs: `TestCIDRLongestPrefixWins` (`/16` vs `/24` vs `/8`) passed **50/50**. Your expanded `TestToFlowsWithRuleSet` (`middle` / `small` / `large`) also passes.
- Name still wins over IP; device `user_tags` still win.

### One leftover that would hit default installs

`GetUserDeviceRuleSet` always calls `deviceRules.Check(ip)` when the device has an IP. If `-user_device_rule_path` is unset, `InitUserDeviceRuleSet` never runs and `deviceRules` stays `nil` → **nil pointer** in `StringAddressRule.Check`.

`parseConfig` always does `GetUserDeviceRuleSet(device.DeviceName, device.DeviceIP)`, so SNMP with a real `device_ip` and no sidecar file would panic on start. Existing tests miss it because they either Init first or leave `DeviceIP` empty (`ParseIP("")` is nil, so Check is skipped).

```go
if deviceRules != nil {
    match := deviceRules.Check(nip)
    ...
}
```

or initialize `deviceRules = NewStringAddressRule()` in the package `var` block / empty-path Init.

Happy to approve as soon as that nil guard is in.

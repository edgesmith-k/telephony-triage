// 모의 스텁 (심볼만). 실제 소스가 아니다.
package com.android.internal.telephony.data;

public class DataSettingsManager {
    private static final String TAG_PREFIX = "DSM-";

    public boolean isDataEnabled() { return true; }
    public boolean isDataRoamingEnabled() { return false; }
    public void setDataEnabled(int reason, boolean enabled) { }
}

// 모의 스텁 (심볼만). 실제 소스가 아니다.
package com.android.internal.telephony.data;

public class DataNetworkController {
    private static final String TAG_PREFIX = "DNC-";

    public void onEvaluateNetworkRequests(int reason) { }
    public DataEvaluation evaluateNetworkRequest(TelephonyNetworkRequest request) { return null; }
    public void onDataEnabledChanged(boolean enabled) { }
}

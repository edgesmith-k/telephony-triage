// 모의 스텁. Android 17에서는 경로가 바뀌었다고 가정한다 (find-symbol 시험용).
package com.android.internal.telephony.data.fail;

public final class DataFailCause {
    public static final int NONE = 0;
    public static final int OPERATOR_BARRED = 8;
    public static String toString(int cause) { return "MOCK"; }
}

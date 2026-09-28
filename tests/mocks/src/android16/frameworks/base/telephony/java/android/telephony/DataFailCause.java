// 모의 스텁. Android 16에서는 frameworks/base/telephony 아래에 있다.
package android.telephony;

public final class DataFailCause {
    public static final int NONE = 0;
    public static final int OPERATOR_BARRED = 8;
    public static String toString(int cause) { return "MOCK"; }
}

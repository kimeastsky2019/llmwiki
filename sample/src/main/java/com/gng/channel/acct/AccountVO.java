package com.gng.channel.acct;

import java.io.Serializable;

/**
 * 계좌 VO
 */
public class AccountVO implements Serializable {

    private static final long serialVersionUID = 1L;

    /** 고객번호 */
    private String custNo;
    /** 출금 계좌번호 */
    private String acctNo;
    /** 입금 계좌번호 */
    private String toAcctNo;
    /** 거래금액 */
    private long trnAmt;
    /** 조회 시작일 */
    private String fromDt;
    /** 조회 종료일 */
    private String toDt;

    public String getCustNo() {
        return custNo;
    }

    public void setCustNo(String custNo) {
        this.custNo = custNo;
    }

    public String getAcctNo() {
        return acctNo;
    }

    public void setAcctNo(String acctNo) {
        this.acctNo = acctNo;
    }

    public String getToAcctNo() {
        return toAcctNo;
    }

    public void setToAcctNo(String toAcctNo) {
        this.toAcctNo = toAcctNo;
    }

    public long getTrnAmt() {
        return trnAmt;
    }

    public void setTrnAmt(long trnAmt) {
        this.trnAmt = trnAmt;
    }

    public String getFromDt() {
        return fromDt;
    }

    public void setFromDt(String fromDt) {
        this.fromDt = fromDt;
    }

    public String getToDt() {
        return toDt;
    }

    public void setToDt(String toDt) {
        this.toDt = toDt;
    }
}

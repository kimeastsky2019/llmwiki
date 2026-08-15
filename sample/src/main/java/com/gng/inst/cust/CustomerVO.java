package com.gng.inst.cust;

import java.io.Serializable;

/**
 * 고객 정보 VO
 */
public class CustomerVO implements Serializable {

    private static final long serialVersionUID = 1L;

    /** 고객번호 */
    private String custNo;
    /** 고객명 */
    private String custNm;
    /** 실명번호(암호화) */
    private String rrno;
    /** 고객등급코드 (공통코드 CD001) */
    private String gradeCd;
    /** 상태코드 01:정상 09:해지 */
    private String statCd;
    /** 휴대전화 */
    private String hpNo;
    /** 검색어 */
    private String searchKeyword;
    /** 페이지 시작 행 */
    private int firstIndex;
    /** 페이지 종료 행 */
    private int lastIndex;

    public String getCustNo() {
        return custNo;
    }

    public void setCustNo(String custNo) {
        this.custNo = custNo;
    }

    public String getCustNm() {
        return custNm;
    }

    public void setCustNm(String custNm) {
        this.custNm = custNm;
    }

    public String getRrno() {
        return rrno;
    }

    public void setRrno(String rrno) {
        this.rrno = rrno;
    }

    public String getGradeCd() {
        return gradeCd;
    }

    public void setGradeCd(String gradeCd) {
        this.gradeCd = gradeCd;
    }

    public String getStatCd() {
        return statCd;
    }

    public void setStatCd(String statCd) {
        this.statCd = statCd;
    }

    public String getHpNo() {
        return hpNo;
    }

    public void setHpNo(String hpNo) {
        this.hpNo = hpNo;
    }

    public String getSearchKeyword() {
        return searchKeyword;
    }

    public void setSearchKeyword(String searchKeyword) {
        this.searchKeyword = searchKeyword;
    }

    public int getFirstIndex() {
        return firstIndex;
    }

    public void setFirstIndex(int firstIndex) {
        this.firstIndex = firstIndex;
    }

    public int getLastIndex() {
        return lastIndex;
    }

    public void setLastIndex(int lastIndex) {
        this.lastIndex = lastIndex;
    }
}

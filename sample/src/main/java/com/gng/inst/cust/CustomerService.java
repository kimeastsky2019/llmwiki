package com.gng.inst.cust;

import java.util.List;
import java.util.Map;

/**
 * 고객 정보 관리 서비스 인터페이스
 */
public interface CustomerService {

    List<CustomerVO> selectCustomerList(CustomerVO searchVO);

    int selectCustomerListTotCnt(CustomerVO searchVO);

    CustomerVO selectCustomer(String custNo);

    List<Map<String, Object>> selectCustomerAccounts(String custNo);

    Map<String, Object> registerCustomer(CustomerVO customerVO);

    Map<String, Object> modifyCustomer(CustomerVO customerVO);

    Map<String, Object> removeCustomer(String custNo);
}

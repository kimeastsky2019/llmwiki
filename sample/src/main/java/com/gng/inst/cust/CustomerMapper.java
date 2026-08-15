package com.gng.inst.cust;

import java.util.List;
import java.util.Map;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/**
 * 고객 정보 매퍼
 */
@Mapper("customerMapper")
public interface CustomerMapper {

    List<CustomerVO> selectCustomerList(CustomerVO searchVO);

    int selectCustomerListTotCnt(CustomerVO searchVO);

    CustomerVO selectCustomer(@Param("custNo") String custNo);

    List<Map<String, Object>> selectCustomerAccounts(@Param("custNo") String custNo);

    int selectCustomerDupCnt(CustomerVO customerVO);

    String selectNextCustNo();

    int selectActiveAccountCnt(@Param("custNo") String custNo);

    int insertCustomer(CustomerVO customerVO);

    int insertCustomerHist(CustomerVO customerVO);

    int updateCustomer(CustomerVO customerVO);

    int deleteCustomer(@Param("custNo") String custNo);
}

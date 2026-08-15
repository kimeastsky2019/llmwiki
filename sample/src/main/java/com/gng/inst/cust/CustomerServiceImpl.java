package com.gng.inst.cust;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import javax.annotation.Resource;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * 고객 정보 관리 서비스 구현
 *
 * 등록/수정/삭제는 선언적 트랜잭션으로 처리하며, 고객 이력(TB_CUST_HIST)을
 * 함께 적재한다. 이력 적재 실패 시 전체 롤백한다.
 */
@Service("customerService")
public class CustomerServiceImpl implements CustomerService {

    @Resource(name = "customerMapper")
    private CustomerMapper customerMapper;

    @Override
    public List<CustomerVO> selectCustomerList(CustomerVO searchVO) {
        return customerMapper.selectCustomerList(searchVO);
    }

    @Override
    public int selectCustomerListTotCnt(CustomerVO searchVO) {
        return customerMapper.selectCustomerListTotCnt(searchVO);
    }

    @Override
    public CustomerVO selectCustomer(String custNo) {
        return customerMapper.selectCustomer(custNo);
    }

    @Override
    public List<Map<String, Object>> selectCustomerAccounts(String custNo) {
        return customerMapper.selectCustomerAccounts(custNo);
    }

    @Override
    @Transactional(propagation = Propagation.REQUIRED, rollbackFor = Exception.class)
    public Map<String, Object> registerCustomer(CustomerVO customerVO) {
        Map<String, Object> result = new HashMap<String, Object>();

        int dupCnt = customerMapper.selectCustomerDupCnt(customerVO);
        if (dupCnt > 0) {
            result.put("code", "CUST-E002");
            result.put("message", "이미 등록된 실명번호입니다.");
            return result;
        }

        String custNo = customerMapper.selectNextCustNo();
        customerVO.setCustNo(custNo);
        customerVO.setStatCd("01");

        customerMapper.insertCustomer(customerVO);
        customerMapper.insertCustomerHist(customerVO);

        result.put("code", "0000");
        result.put("custNo", custNo);
        return result;
    }

    @Override
    @Transactional(propagation = Propagation.REQUIRED, rollbackFor = Exception.class)
    public Map<String, Object> modifyCustomer(CustomerVO customerVO) {
        Map<String, Object> result = new HashMap<String, Object>();

        CustomerVO before = customerMapper.selectCustomer(customerVO.getCustNo());
        if (before == null) {
            result.put("code", "CUST-E001");
            result.put("message", "존재하지 않는 고객입니다.");
            return result;
        }

        int updated = customerMapper.updateCustomer(customerVO);
        if (updated == 0) {
            throw new IllegalStateException("고객 정보 수정에 실패했습니다.");
        }
        customerMapper.insertCustomerHist(customerVO);

        result.put("code", "0000");
        return result;
    }

    @Override
    @Transactional(propagation = Propagation.REQUIRED, rollbackFor = Exception.class)
    public Map<String, Object> removeCustomer(String custNo) {
        Map<String, Object> result = new HashMap<String, Object>();

        int acctCnt = customerMapper.selectActiveAccountCnt(custNo);
        if (acctCnt > 0) {
            result.put("code", "CUST-E003");
            result.put("message", "거래중인 계좌가 있어 삭제할 수 없습니다.");
            return result;
        }

        customerMapper.deleteCustomer(custNo);
        result.put("code", "0000");
        return result;
    }
}

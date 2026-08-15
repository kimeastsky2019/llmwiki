package com.gng.inst.cust;

import java.util.List;
import java.util.Map;

import javax.annotation.Resource;

import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseBody;

import com.gng.common.code.CodeService;

/**
 * 고객 정보 관리
 *
 * 기관계 창구단말에서 고객 기본정보를 조회/등록/수정하는 화면을 담당한다.
 * 고객 등급은 공통코드(CD001)를 참조한다.
 *
 * @author 김동호
 */
@Controller
@RequestMapping("/inst/cust")
public class CustomerController {

    @Resource(name = "customerService")
    private CustomerService customerService;

    @Resource(name = "codeService")
    private CodeService codeService;

    /**
     * 고객 목록 조회 화면
     */
    @GetMapping("/list.do")
    public String list(CustomerVO searchVO, Model model) {
        List<CustomerVO> custList = customerService.selectCustomerList(searchVO);
        int totalCount = customerService.selectCustomerListTotCnt(searchVO);

        model.addAttribute("custList", custList);
        model.addAttribute("totalCount", totalCount);
        model.addAttribute("gradeCodes", codeService.selectCodeList("CD001"));
        return "inst/cust/customerList";
    }

    /**
     * 고객 상세 조회
     */
    @GetMapping("/detail.do")
    public String detail(CustomerVO searchVO, Model model) {
        CustomerVO customer = customerService.selectCustomer(searchVO.getCustNo());
        if (customer == null) {
            model.addAttribute("errorCode", "CUST-E001");
            model.addAttribute("errorMsg", "존재하지 않는 고객입니다.");
            return "common/error";
        }
        model.addAttribute("customer", customer);
        model.addAttribute("acctList", customerService.selectCustomerAccounts(searchVO.getCustNo()));
        return "inst/cust/customerDetail";
    }

    /**
     * 고객 등록
     */
    @PostMapping("/insert.do")
    @ResponseBody
    public Map<String, Object> insert(CustomerVO customerVO) {
        return customerService.registerCustomer(customerVO);
    }

    /**
     * 고객 정보 수정
     */
    @PostMapping("/update.do")
    @ResponseBody
    public Map<String, Object> update(CustomerVO customerVO) {
        return customerService.modifyCustomer(customerVO);
    }

    /**
     * 고객 삭제 (논리 삭제)
     */
    @PostMapping("/delete.do")
    @ResponseBody
    public Map<String, Object> delete(CustomerVO customerVO) {
        return customerService.removeCustomer(customerVO.getCustNo());
    }
}

package com.gng.common.code;

import java.util.List;
import java.util.Map;

import javax.annotation.Resource;

import org.springframework.stereotype.Service;

/**
 * 공통코드 조회 서비스
 *
 * 전 계층에서 공유하는 공통코드(TB_COM_CODE)를 조회한다.
 */
@Service("codeService")
public class CodeService {

    @Resource(name = "codeMapper")
    private CodeMapper codeMapper;

    /**
     * 코드그룹별 공통코드 목록 조회
     */
    public List<Map<String, Object>> selectCodeList(String cdGrp) {
        return codeMapper.selectCodeList(cdGrp);
    }

    /**
     * 코드명 단건 조회
     */
    public String selectCodeName(String cdGrp, String cd) {
        return codeMapper.selectCodeName(cdGrp, cd);
    }
}

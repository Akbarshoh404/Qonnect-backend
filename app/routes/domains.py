"""
Custom domain management routes
"""
import logging
import dns.resolver

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

from app.extensions import db, limiter
from app.models import CustomDomain
from app.utils.validators import validate_domain

logger = logging.getLogger(__name__)
domains_bp = Blueprint("domains", __name__, url_prefix="/api/domains")


@domains_bp.route("", methods=["GET"])
@login_required
def list_domains():
    """List all custom domains for the current user."""
    domains = CustomDomain.query.filter_by(user_id=current_user.id).all()
    return jsonify({"domains": [d.to_dict() for d in domains]})


@domains_bp.route("", methods=["POST"])
@login_required
@limiter.limit("10 per hour")
def add_domain():
    """Add a new custom domain."""
    data = request.json or {}
    raw_domain = data.get("domain", "").strip()

    valid, result = validate_domain(raw_domain)
    if not valid:
        return jsonify({"error": result}), 400

    normalized_domain = result  # validate_domain returns normalized on success

    # Check if domain already exists
    existing = CustomDomain.query.filter_by(domain=normalized_domain).first()
    if existing:
        if existing.user_id == current_user.id:
            return jsonify({"error": "You've already added this domain"}), 409
        else:
            return jsonify({"error": "This domain is already registered with another account"}), 409

    domain = CustomDomain(
        user_id=current_user.id,
        domain=normalized_domain,
        verification_token=CustomDomain.generate_verification_token(),
    )
    db.session.add(domain)
    db.session.commit()

    logger.info(f"Added domain {normalized_domain} for user {current_user.id}")
    return jsonify({"domain": domain.to_dict()}), 201


@domains_bp.route("/<int:domain_id>", methods=["GET"])
@login_required
def get_domain(domain_id: int):
    """Get domain details including verification instructions."""
    domain = CustomDomain.query.filter_by(
        id=domain_id, user_id=current_user.id
    ).first_or_404()
    return jsonify({"domain": domain.to_dict()})


@domains_bp.route("/<int:domain_id>/verify", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def verify_domain(domain_id: int):
    """
    Trigger domain ownership verification via DNS TXT record check.
    
    The user must add a TXT record:
    _qonnect-verify.<domain>  TXT  <verification_token>
    """
    domain = CustomDomain.query.filter_by(
        id=domain_id, user_id=current_user.id
    ).first_or_404()

    if domain.verified:
        return jsonify({"domain": domain.to_dict(), "message": "Already verified"})

    expected_token = domain.verification_token
    record_name = f"_qonnect-verify.{domain.domain}"

    try:
        answers = dns.resolver.resolve(record_name, "TXT")
        for rdata in answers:
            for string in rdata.strings:
                txt_value = string.decode("utf-8", errors="replace")
                if txt_value == expected_token:
                    domain.verified = True
                    db.session.commit()
                    logger.info(f"Domain verified: {domain.domain} for user {current_user.id}")
                    return jsonify({
                        "domain": domain.to_dict(),
                        "message": "Domain verified successfully!",
                    })

        return jsonify({
            "error": "Verification TXT record not found or doesn't match.",
            "expected_record": record_name,
            "expected_value": expected_token,
        }), 400

    except dns.resolver.NXDOMAIN:
        return jsonify({
            "error": f"DNS record not found: {record_name}",
            "hint": "DNS changes can take up to 48 hours to propagate.",
        }), 400
    except dns.resolver.NoAnswer:
        return jsonify({
            "error": f"No TXT records found for {record_name}",
            "hint": "Make sure you've added the TXT record exactly as shown.",
        }), 400
    except Exception as e:
        logger.error(f"DNS verification error for {domain.domain}: {e}")
        return jsonify({"error": "DNS lookup failed. Please try again."}), 500


@domains_bp.route("/<int:domain_id>", methods=["DELETE"])
@login_required
def delete_domain(domain_id: int):
    """Remove a custom domain."""
    domain = CustomDomain.query.filter_by(
        id=domain_id, user_id=current_user.id
    ).first_or_404()

    domain_name = domain.domain
    db.session.delete(domain)
    db.session.commit()

    logger.info(f"Deleted domain {domain_name} for user {current_user.id}")
    return jsonify({"message": f"Domain {domain_name} removed"})
